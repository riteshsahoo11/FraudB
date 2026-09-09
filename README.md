# FraudB

FraudB is a machine learning-powered Django application designed for detecting and predicting fraudulent transactions. 

## Features

- **Machine Learning Integration**: Utilizes `scikit-learn` for predictive fraud modeling (Gradient Boosting, etc.).
- **User Authentication**: Built-in accounts module for secure signups and logins.
- **RESTful API**: Allows external integrations via the `api` app.
- **Core Dashboard & Analytics**: Intuitive frontend views to monitor predictions, test data, and review model analytics.
- **Data Preprocessing & Evaluation**: Structured `ml` module dedicated to data handling, encoding, and model evaluation.

## Project Structure

- `accounts/` - Handles user authentication, registration, and profile management.
- `api/` - Houses the REST API endpoints and routing logic.
- `core/` - Contains the main frontend views, templates, and dashboard components.
- `ml/` - Contains all machine learning models, encoders, datasets, training scripts, and preprocessing logic.
- `project_settings/` - Core Django settings and configuration.

## Installation & Setup

1. **Clone the repository:**
   ```bash
   git clone https://github.com/riteshsahoo11/FraudB.git
   cd FraudB
   ```

2. **Create a virtual environment (Optional but recommended):**
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install the dependencies:**
   ```bash
   cd FrontendBackend/FrontendBackend
   pip install -r requirements.txt
   ```

4. **Set up Environment Variables:**
   Create a `.env` file in the `FrontendBackend/FrontendBackend` directory with the necessary database and Django configuration variables.

5. **Run Database Migrations:**
   ```bash
   python manage.py migrate
   ```

6. **Run the Development Server:**
   ```bash
   python manage.py runserver
   ```

## Technologies Used

- **Backend**: Python 3, Django 5.1
- **Machine Learning**: Scikit-Learn, Pandas, NumPy, Joblib, SciPy
- **Database**: Django ORM (configured in `.env` / MongoDB support available via PyMongo)
- **Frontend**: HTML5, CSS3, JavaScript (Django Templates)

## Contributing

Pull requests are welcome. For major changes, please open an issue first to discuss what you would like to change.
