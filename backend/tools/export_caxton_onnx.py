"""
backend/tools/export_caxton_onnx.py
------------------------------------
Exports a Cambridge CAXTON (RAN-56) PyTorch checkpoint to ONNX format
for low-latency CPU inference on Raspberry Pi 4B/5 via onnxruntime.

Usage:
  python backend/tools/export_caxton_onnx.py --checkpoint path/to/caxton.ckpt \
                                             --output backend/edge/models/caxton.onnx

The exported ONNX model takes input:
  [batch_size, 3, 224, 224] (float32, ImageNet normalised)
and produces 4 output tensors corresponding to:
  1. Flow rate state (under, optimal, over)
  2. Speed state (slow, optimal, fast)
  3. Z-offset state (too close, optimal, too far)
  4. Temperature state (too cold, optimal, too hot)
"""

import argparse
import os
import sys

def main():
    parser = argparse.ArgumentParser(description="Export CAXTON checkpoint to ONNX")
    parser.add_argument("--checkpoint", required=True, help="Path to PyTorch .ckpt file")
    parser.add_argument("--output", default="backend/edge/models/caxton.onnx", help="Output .onnx path")
    parser.add_argument("--caxton-repo", default="../research_repos/cam_caxton", help="Path to cam_caxton repo")
    args = parser.parse_args()

    try:
        import torch
        import torch.nn as nn
    except ImportError:
        print("🔴 PyTorch is required to export to ONNX: pip install torch")
        sys.exit(1)

    # Add CAXTON src to sys.path
    src_path = os.path.join(args.caxton_repo, "src")
    if os.path.isdir(src_path):
        sys.path.insert(0, src_path)

    try:
        from model.residual_attention_network import ResidualAttentionModel_56
    except ImportError:
        print(f"🔴 Could not import ResidualAttentionModel_56 from {src_path}")
        sys.exit(1)

    class CaxtonInferenceModel(nn.Module):
        def __init__(self, num_classes=3):
            super().__init__()
            self.attention_model = ResidualAttentionModel_56()
            num_ftrs = self.attention_model.fc.in_features
            self.attention_model.fc = nn.Identity()
            self.fc1 = nn.Linear(num_ftrs, num_classes)
            self.fc2 = nn.Linear(num_ftrs, num_classes)
            self.fc3 = nn.Linear(num_ftrs, num_classes)
            self.fc4 = nn.Linear(num_ftrs, num_classes)

        def forward(self, x):
            feat = self.attention_model(x)
            return self.fc1(feat), self.fc2(feat), self.fc3(feat), self.fc4(feat)

    print(f"🧠 Loading weights from: {args.checkpoint}")
    ckpt = torch.load(args.checkpoint, map_location="cpu")
    state_dict = ckpt.get("state_dict", ckpt)

    # Clean state_dict keys if saved from PyTorch Lightning
    cleaned_state_dict = {}
    for k, v in state_dict.items():
        if k.startswith("attention_model.") or k.startswith("fc"):
            cleaned_state_dict[k] = v

    model = CaxtonInferenceModel()
    model.load_state_dict(cleaned_state_dict, strict=False)
    model.eval()

    dummy_input = torch.randn(1, 3, 224, 224)
    os.makedirs(os.path.dirname(args.output), exist_ok=True)

    print(f"📦 Exporting ONNX to: {args.output}")
    torch.onnx.export(
        model,
        dummy_input,
        args.output,
        input_names=["input_image"],
        output_names=["flow_logits", "speed_logits", "z_logits", "temp_logits"],
        dynamic_axes={"input_image": {0: "batch_size"}},
        opset_version=14,
    )
    print("✅ Export complete!")

if __name__ == "__main__":
    main()
