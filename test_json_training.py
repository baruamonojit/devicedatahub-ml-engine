#!/usr/bin/env python3
"""
Test script to train and validate model using JSON training data.

Usage:
    python test_json_training.py
"""

import sys
import os
from pathlib import Path

# Add project to path
sys.path.insert(0, str(Path(__file__).parent))

from devicedatahub_ml_engine.train import main as train_main
import argparse


def test_json_training():
    """Test training from JSON data."""
    print("="*70)
    print("Testing JSON Training Data Integration")
    print("="*70)
    
    # Setup paths
    project_root = Path(__file__).parent
    json_data_path = project_root / "data" / "ml_radio_stats_train_1000.json"
    model_output_path = project_root / "model_artifacts" / "test_model.pkl"
    
    print(f"\n📂 Project root: {project_root}")
    print(f"📄 JSON data: {json_data_path}")
    print(f"💾 Model output: {model_output_path}")
    
    # Check if JSON file exists
    if not json_data_path.exists():
        print(f"\n❌ ERROR: JSON training data not found at {json_data_path}")
        return False
    
    print(f"\n✅ JSON file found")
    
    # Create model directory
    model_output_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Train model
    print(f"\n🚀 Training model from JSON data...")
    try:
        args = argparse.Namespace(
            data=str(json_data_path),
            out=str(model_output_path)
        )
        train_main(args)
        
        # Check if model was saved
        if model_output_path.exists():
            model_size = model_output_path.stat().st_size
            print(f"\n✅ Model successfully created")
            print(f"   - Path: {model_output_path}")
            print(f"   - Size: {model_size / 1024 / 1024:.2f} MB")
            return True
        else:
            print(f"\n❌ Model file not created")
            return False
            
    except Exception as e:
        print(f"\n❌ Training failed: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == '__main__':
    success = test_json_training()
    sys.exit(0 if success else 1)
