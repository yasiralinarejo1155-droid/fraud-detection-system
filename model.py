import tensorflow as tf
from tensorflow import keras
import numpy as np
import os

class ScreenshotDetector:
    def __init__(self, model_path='model/screenshot_model.h5'):
        """
        Initialize the model
        """
        self.model = None
        self.model_path = model_path
        self.load_model()
        
    def load_model(self):
        """
        Load the trained model
        """
        try:
            if os.path.exists(self.model_path):
                self.model = keras.models.load_model(self.model_path)
                print(f"Model loaded successfully from {self.model_path}")
            else:
                print(f"Model not found at {self_path}. Using dummy model.")
                self.create_dummy_model()
        except Exception as e:
            print(f"Error loading model: {e}")
            self.create_dummy_model()
    
    def create_dummy_model(self):
        """
        Create a dummy model if no trained model is available
        """
        from tensorflow.keras import layers, models
        
        # Simple CNN for demonstration
        model = models.Sequential([
            layers.Conv2D(32, (3, 3), activation='relu', input_shape=(224, 224, 3)),
            layers.MaxPooling2D((2, 2)),
            layers.Conv2D(64, (3, 3), activation='relu'),
            layers.MaxPooling2D((2, 2)),
            layers.Conv2D(128, (3, 3), activation='relu'),
            layers.MaxPooling2D((2, 2)),
            layers.Flatten(),
            layers.Dense(128, activation='relu'),
            layers.Dense(1, activation='sigmoid')
        ])
        
        model.compile(optimizer='adam',
                     loss='binary_crossentropy',
                     metrics=['accuracy'])
        
        self.model = model
        print("Created dummy model for testing")
    
    def predict(self, image_array):
        """
        Make prediction on image
        Returns: (prediction, confidence, class_label)
        """
        try:
            if self.model is None:
                self.load_model()
            
            # Make prediction
            prediction = self.model.predict(image_array, verbose=0)
            
            # Get confidence and class
            confidence = float(prediction[0][0])
            
            # Threshold at 0.5
            if confidence > 0.5:
                class_label = "FAKE"
                final_confidence = confidence
            else:
                class_label = "REAL"
                final_confidence = 1 - confidence
            
            # Convert to percentage
            confidence_percent = round(final_confidence * 100, 2)
            
            return {
                'prediction': class_label,
                'confidence': confidence_percent,
                'raw_score': float(confidence),
                'is_fake': class_label == "FAKE"
            }
            
        except Exception as e:
            print(f"Error during prediction: {e}")
            return {
                'prediction': "ERROR",
                'confidence': 0,
                'raw_score': 0,
                'is_fake': False,
                'error': str(e)
            }
    
    def get_model_info(self):
        """
        Get model information
        """
        if self.model:
            return {
                'model_type': str(type(self.model)),
                'input_shape': self.model.input_shape,
                'output_shape': self.model.output_shape,
                'layers': len(self.model.layers)
            }
        return {"status": "Model not loaded"}