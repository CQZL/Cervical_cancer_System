import os
import torch
import numpy as np
from openslide import OpenSlide
from PIL import Image
from skimage import color, exposure, feature
from AICervicals.prediction import (
    load_image_paths,
    preprocess_images,
    batch_predict,
    draw_boxes_and_save
)
from AICervicals.predict import densenet_fpn_backbone, FasterRCNN

# ==== 常量配置 ====
MODEL_PATH = r"C:\Project\cervical_cell\\AICervicals\\results\saved_models\best_densenet152.pth"
CLASS_NAMES = ["Background", "Positive"]
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
PATCH_SIZE = 2048
BATCH_SIZE = 20
THRESHOLD = 0.5

# ==== Patch过滤配置 ====
FILTER_CONFIG = {
    "enable_blank_check": True,
    "white_thresh": 220,
    "black_thresh": 20,
    "enable_std": True,
    "std_thresh": 11,
    "enable_entropy": True,
    "entropy_thresh": 4
}


class PatchFilter:
    def __init__(self, config):
        # 将配置字典转换为实例属性
        self.config = config
        for key, value in config.items():
            setattr(self, key, value)

        # 设置默认值（防止配置缺失）
        self.enable_blank_check = config.get('enable_blank_check', True)
        self.white_thresh = config.get('white_thresh', 220)
        self.black_thresh = config.get('black_thresh', 20)
        self.enable_std = config.get('enable_std', False)
        self.std_thresh = config.get('std_thresh', 11)
        self.enable_entropy = config.get('enable_entropy', False)
        self.entropy_thresh = config.get('entropy_thresh', 4.5)
        self.enable_saturation = config.get('enable_saturation', False)
        self.saturation_thresh = config.get('saturation_thresh', 0.15)
        self.enable_texture = config.get('enable_texture', False)
        self.contrast_thresh = config.get('contrast_thresh', 40)

    def validate(self, rgb_patch):
        """统一验证接口，返回是否通过和拒绝原因"""
        reject_reasons = []

        # 基础空白检查
        if self.enable_blank_check:
            if self._is_blank(rgb_patch):
                reject_reasons.append("blank")
                return False, reject_reasons

        # 颜色标准差检测
        if self.enable_std:
            std_pass, std_msg = self._check_color_std(rgb_patch)
            if not std_pass:
                reject_reasons.append(std_msg)

        # 图像熵检测
        if self.enable_entropy:
            entropy_pass, entropy_msg = self._check_entropy(rgb_patch)
            if not entropy_pass:
                reject_reasons.append(entropy_msg)

        # 饱和度检测
        if self.enable_saturation:
            saturation_pass, saturation_msg = self._check_saturation(rgb_patch)
            if not saturation_pass:
                reject_reasons.append(saturation_msg)

        # 纹理检测
        if self.enable_texture:
            texture_pass, texture_msg = self._check_texture(rgb_patch)
            if not texture_pass:
                reject_reasons.append(texture_msg)

        return len(reject_reasons) == 0, reject_reasons

    def _is_blank(self, patch):
        if np.all(patch >= self.white_thresh):
            return True
        if np.all(patch <= self.black_thresh):
            return True
        return False

    def _check_color_std(self, patch):
        std = np.mean([np.std(patch[:, :, i]) for i in range(3)])
        return std >= self.std_thresh, f"std_low({std:.1f}<{self.std_thresh})"

    def _check_entropy(self, patch):
        gray = color.rgb2gray(patch)
        hist = exposure.histogram(gray, nbins=256)[0]
        hist = hist / hist.sum()
        entropy = -np.sum(hist * np.log2(hist + 1e-7))
        return entropy >= self.entropy_thresh, f"entropy_low({entropy:.2f}<{self.entropy_thresh})"

    def _check_saturation(self, patch):
        hsv = color.rgb2hsv(patch)
        saturation = np.mean(hsv[:, :, 1])
        return saturation >= self.saturation_thresh, f"saturation_low({saturation:.2f}<{self.saturation_thresh})"

    def _check_texture(self, patch):
        gray = (color.rgb2gray(patch) * 255).astype(np.uint8)
        glcm = feature.graycomatrix(gray, [1], [0], levels=256, symmetric=True, normed=True)
        contrast = feature.graycoprops(glcm, 'contrast')[0, 0]
        return contrast >= self.contrast_thresh, f"contrast_low({contrast:.1f}<{self.contrast_thresh})"


from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm import tqdm
import numpy as np
import os
from openslide import OpenSlide
from PIL import Image
from itertools import product


class WSIPreprocessor:
    def __init__(self, patch_size=2048, num_workers=8):
        self.patch_size = patch_size
        self.num_workers = num_workers  # 线程数量

    def process_patch(self, slide_path, x, y, output_dir):
        """单个patch处理函数（线程安全）"""
        try:
            slide = OpenSlide(slide_path)  # 每个线程独立打开slide
            patch = slide.read_region(
                (x, y), 0,
                (self.patch_size, self.patch_size)
            )
            rgb_patch = np.array(patch.convert("RGB"))
            slide.close()  # 及时关闭

            # 质量验证
            filter = PatchFilter(FILTER_CONFIG)
            is_valid, reasons = filter.validate(rgb_patch)

            # 保存路径
            save_dir = os.path.join(output_dir, "accepted" if is_valid else "rejected")
            os.makedirs(save_dir, exist_ok=True)

            filename = f"{os.path.basename(slide_path)}_{x}_{y}.png"
            Image.fromarray(rgb_patch).save(os.path.join(save_dir, filename))

            return is_valid

        except Exception as e:
            print(f"Error processing patch ({x}, {y}): {str(e)}")
            return False

    def process(self, wsi_path, output_dir):
        try:
            slide = OpenSlide(wsi_path)
        except Exception as e:
            print(f"打开失败 {wsi_path}: {e}")
            return

        width, height = slide.dimensions
        slide.close()  # 主线程关闭slide

        # 计算坐标（保证patch完整）
        max_x = width - self.patch_size
        max_y = height - self.patch_size

        x_coords = np.arange(0, max_x + 1, self.patch_size)
        y_coords = np.arange(0, max_y + 1, self.patch_size)

        # 处理最后一个坐标点
        x_coords = np.append(x_coords[:-1], max_x) if len(x_coords) > 0 else [max_x]
        y_coords = np.append(y_coords[:-1], max_y) if len(y_coords) > 0 else [max_y]

        total_patches = len(x_coords) * len(y_coords)
        valid_count = 0

        # 多线程处理
        with ThreadPoolExecutor(max_workers=self.num_workers) as executor:
            futures = []
            with tqdm(total=total_patches,
                      desc=f"Processing {os.path.basename(wsi_path)}",
                      unit="patch",
                      dynamic_ncols=True) as pbar:

                # 提交任务
                for x, y in product(x_coords, y_coords):
                    future = executor.submit(
                        self.process_patch,
                        wsi_path,
                        x,
                        y,
                        output_dir
                    )
                    futures.append(future)

                # 收集结果
                for future in as_completed(futures):
                    valid = future.result()
                    if valid:
                        valid_count += 1
                    pbar.update(1)
                    pbar.set_postfix({
                        "Valid": f"{valid_count}/{pbar.n}/{total_patches}",
                        "Status": "Processing"
                    })

        print(f"\n处理完成: {wsi_path} (有效块: {valid_count}/{total_patches})")

class ModelPredictor:
    def __init__(self, model_path=MODEL_PATH):
        self.model = self._load_model(model_path).to(DEVICE).eval()

    def _load_model(self, model_path):
        """模型加载器"""
        backbone = densenet_fpn_backbone("densenet121", pretrained=False)
        model = FasterRCNN(backbone, num_classes=2)
        model.load_state_dict(torch.load(model_path))
        return model

    def predict(self, image_dir, output_dir):
        """执行预测"""
        image_paths = load_image_paths(image_dir)
        dataloader = preprocess_images(image_paths, batch_size=BATCH_SIZE)
        predictions = batch_predict(self.model, dataloader, device=DEVICE)
        draw_boxes_and_save(
            predictions,
            output_dir,
            CLASS_NAMES,
            threshold=THRESHOLD
        )


class Pipeline:
    def __init__(self):
        self.preprocessor = WSIPreprocessor()
        self.predictor = ModelPredictor()

    def run(self, image_path):
        """完整处理流程"""
        try:
            # 预处理阶段
            base_name = os.path.splitext(os.path.basename(image_path))[0]
            output_base = os.path.join(os.path.dirname(image_path), base_name)
            os.makedirs(output_base, exist_ok=True)

            self.preprocessor.process(image_path, output_base)

            # 预测阶段
            accepted_dir = os.path.join(output_base, "accepted")
            result_dir = os.path.join(output_base, "result")
            os.makedirs(result_dir, exist_ok=True)

            self.predictor.predict(accepted_dir, result_dir)
            print(f"处理完成: {image_path} → 结果保存至 {result_dir}")

        except Exception as e:
            print(f"处理失败: {image_path} ({str(e)})")


# ==== 使用示例 ====
if __name__ == "__main__":
    pipeline = Pipeline()
    image_path = "your_image_path.svs"  # 替换为实际路径
    pipeline.run(image_path)