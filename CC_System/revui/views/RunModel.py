import os
import numpy as np
from openslide import OpenSlide
# The path can also be read from a config file, etc.

import os
from AICervicals.prediction import load_image_paths,preprocess_images,batch_predict,draw_boxes_and_save
from PIL import Image
from skimage import color, exposure, feature
from AICervicals.predict import  *

class PatchFilter:
    def __init__(self,
                 # 基础参数
                 enable_blank_check=True,
                 white_thresh=240,
                 black_thresh=15,

                 # 可选过滤方法
                 enable_std=False,
                 std_thresh=20,

                 enable_entropy=False,
                 entropy_thresh=4.5,

                 enable_saturation=False,
                 saturation_thresh=0.15,

                 enable_texture=False,
                 contrast_thresh=40):

        # 基础过滤配置
        self.enable_blank_check = enable_blank_check
        self.white_thresh = white_thresh
        self.black_thresh = black_thresh

        # 各功能模块开关及参数
        self.enable_std = enable_std
        self.std_thresh = std_thresh

        self.enable_entropy = enable_entropy
        self.entropy_thresh = entropy_thresh

        self.enable_saturation = enable_saturation
        self.saturation_thresh = saturation_thresh

        self.enable_texture = enable_texture
        self.contrast_thresh = contrast_thresh

    def validate_patch(self, rgb_patch):
        """模块化质量检测"""
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


def save_patch(patch, output_dir, base_name, idx, rejected=False, reasons=None):
    """增强版保存函数，支持分类保存"""
    # 创建子目录
    save_dir = os.path.join(output_dir, "rejected" if rejected else "accepted")
    os.makedirs(save_dir, exist_ok=True)

    # 生成文件名
    if rejected and reasons:
        reason_tag = "_".join([r.split("(")[0] for r in reasons])[:50]  # 截断过长的原因
        filename = f"{base_name}_rejected_{idx:04d}_{reason_tag}.png"
    else:
        filename = f"{base_name}_accepted_{idx:04d}.png"

    Image.fromarray(patch).save(os.path.join(save_dir, filename))


def process_wsi(wsi_path, output_dir, patch_size=2048, filter_config=None):
    """增强版处理函数，支持保存被过滤的patch"""
    try:
        slide = OpenSlide(wsi_path)
    except Exception as e:
        print(f"无法打开 {wsi_path}: {e}")
        return

    width, height = slide.dimensions
    filter = PatchFilter(**filter_config) if filter_config else PatchFilter()
    valid_count = 0
    rejected_count = 0

    for y in range(0, height, patch_size):
        for x in range(0, width, patch_size):
            # 读取图像块
            patch = slide.read_region((x, y), 0,
                                      (min(patch_size, width - x), min(patch_size, height - y)))
            rgb_patch = np.array(patch.convert("RGB"))

            # 质量验证
            is_valid, reject_reasons = filter.validate_patch(rgb_patch)

            if not is_valid:
                print(f"过滤 [{os.path.basename(wsi_path)}] ({x},{y}) - {', '.join(reject_reasons)}")
                save_patch(rgb_patch, output_dir,
                           os.path.splitext(os.path.basename(wsi_path))[0],
                           rejected_count,
                           rejected=True,
                           reasons=reject_reasons)
                rejected_count += 1
                continue

            # 保存有效块
            save_patch(rgb_patch, output_dir,
                       os.path.splitext(os.path.basename(wsi_path))[0],
                       valid_count)
            valid_count += 1

    print(f"处理完成 {os.path.basename(wsi_path)}:")
    print(f" 有效块: {valid_count} | 过滤块: {rejected_count}")


# 批量处理函数保持不变
def batch_process(image_path, output_base, patch_size=2048, filter_config=None):
    """批量处理整个文件夹"""
    "加入一个提取文件名"
    filename =  os.path.basename(image_path)
    output_dir = os.path.join(output_base, filename)
    process_wsi(image_path, output_dir, patch_size, filter_config)

class RunModel:
    def __init__(self):
        self.run_model(image_path=image_path)

    def run_model(self,image_path):
        from MainWidget import MainWidget
        self.main = MainWidget()

        # 图片链接,后期换成地址队列

        #image = self.main.lead_image(image)
        #if image is None:
        #    raise ValueError("No image loaded")
        #image_path = self.main.lead_image().fileName()
        #先进行切图，并保留符合要求的patch
        CUSTOM_FILTER = {
            "enable_blank_check": True,
            "white_thresh": 220,
            "black_thresh": 20,
            "enable_std": True,
            "std_thresh": 11,
            "enable_entropy": True,
            "entropy_thresh": 4
        }

        # 运行配置
        batch_process(
            image_path=image_path,
            output_base=image_path,
            patch_size=2048,
            filter_config=CUSTOM_FILTER
        )
        #进行预测
        model_path = "C:\Project\cervical_cell\AttFPN-Ovarian-Cancer-master\\results\saved_models\\best_densenet152.pth"
        # image_path = "C:\Project\cervical_cell\AttFPN-Ovarian-Cancer-master\FYBJtest\\18372320001057SCC_accepted_0232.png"
        # output_path = "output_image_with_boxes.jpg"
        image_dir = os.path.join(image_path,"accept")
        output_dir = os.path.join(image_path,"result")
        num_classes = 2  # 类别数（背景 + 目标）
        class_names = ["Background", "Positive"]  # 类别名称列表
        batch_size = 20  # 批次大小
        device = "cuda" if torch.cuda.is_available() else "cpu"

        # 加载模型
        #from ..utils.backbone_utils import resnet_fpn_backbone
        #from faster_rcnn import FasterRCNN

        # backbone = resnet_fpn_backbone("den", pretrained=False)
        backbone = densenet_fpn_backbone("densenet121", pretrained=False)
        model = FasterRCNN(backbone, num_classes=num_classes)
        model.load_state_dict(torch.load(model_path))
        model.eval()

        # 加载图像路径
        image_paths = load_image_paths(image_dir)

        # 批量预处理
        dataloader = preprocess_images(image_paths, batch_size=batch_size)

        # 批量推理
        predictions = batch_predict(model, dataloader, device=device)

        # 绘制边界框并保存结果
        draw_boxes_and_save(predictions, output_dir, class_names, threshold=0.5)

        print("批量化处理完成！结果已保存到:", output_dir)

        # 接入模型-运行
        print(image_path)



