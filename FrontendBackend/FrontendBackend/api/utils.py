"""
Utility functions for API app
"""
import pandas as pd
import numpy as np
import logging
from django.conf import settings
from api.models import Prediction  # Import the Prediction model

logger = logging.getLogger(__name__)


def process_transaction_file(file_upload):
    """Process uploaded transaction file - placeholder for future ML integration"""
    try:
        # Read the file
        if file_upload.file_name.endswith('.csv'):
            df = pd.read_csv(file_upload.file_path)
        else:
            # Assume Excel
            df = pd.read_excel(file_upload.file_path)
        
        # TODO: Add your ML model integration here in the future
        # For now, we'll just create placeholder predictions
        predictions, probabilities = generate_placeholder_predictions(df)
        
        # Update file_upload record count
        file_upload.record_count = len(df)
        file_upload.processed_count = len(df)
        file_upload.status = 'completed'
        file_upload.save()
        
        # Save predictions (placeholder)
        for idx, row in df.iterrows():
            prediction_data = {
                'amount': row.get('amount', 0),
                'transaction_type': row.get('type', 'CASH_OUT'),
                'features': {}  # Placeholder for actual features
            }
            
            # Create a placeholder prediction
            Prediction.objects.create(
                user=file_upload.user,
                file_upload=file_upload,
                transaction_id=row.get('transaction_id', f'txn_{idx}'),
                prediction_data=prediction_data,
                predicted_label=int(predictions[idx]),
                confidence=float(probabilities[idx])
            )
        
        return True
        
    except Exception as e:
        logger.error(f"Error processing file {file_upload.file_name}: {str(e)}")
        file_upload.status = 'failed'
        file_upload.save()
        return False


def generate_placeholder_predictions(df):
    """
    Generate placeholder predictions until ML model is integrated
    Replace this function with actual model prediction code later
    """
    # Placeholder logic - replace with actual model prediction
    n_samples = len(df)
    predictions = np.zeros(n_samples)  # All legitimate by default
    
    # Simple rule-based placeholder for demonstration
    if 'amount' in df.columns:
        # Mark transactions over 200,000 as suspicious (placeholder)
        high_amount_indices = df[df['amount'] > 200000].index
        predictions[high_amount_indices] = 1
    
    # Placeholder confidence scores
    probabilities = np.random.uniform(0.7, 0.99, n_samples)
    
    return predictions, probabilities


def preprocess_data(df):
    """
    Preprocess the transaction data.
    TODO: Implement actual preprocessing for your ML model
    """
    # Placeholder preprocessing - implement based on your model requirements
    processed_df = df.copy()
    
    # Example preprocessing steps (customize based on your needs)
    numeric_columns = ['amount', 'oldbalanceOrg', 'newbalanceOrig', 'oldbalanceDest', 'newbalanceDest']
    
    for col in numeric_columns:
        if col in processed_df.columns:
            # Fill missing values with median
            if processed_df[col].isnull().any():
                processed_df[col] = processed_df[col].fillna(processed_df[col].median())
    
    # TODO: Add more preprocessing steps as needed for your model
    
    return processed_df


# TODO: Add this function when you have your ML model ready
def load_ml_model(model_path):
    """
    Load the ML model from the specified path.
    Implement this function when you have your model ready.
    """
    # Example implementation (commented out):
    # import joblib
    # model = joblib.load(model_path)
    # return model
    
    logger.warning("ML model loading not implemented yet. Using placeholder predictions.")
    return None


# TODO: Add this function when you have your ML model ready
def predict_with_model(model, data):
    """
    Make predictions using the ML model.
    Implement this function when you have your model ready.
    """
    # Example implementation (commented out):
    # predictions = model.predict(data)
    # probabilities = model.predict_proba(data)
    # return predictions, probabilities
    
    logger.warning("ML model prediction not implemented yet. Using placeholder predictions.")
    return generate_placeholder_predictions(data)