# ZenFinance
A Personal Finance Auditing tool.

## 🚀 How to Run the App

You can launch the app in one go using the built-in startup script, or run it manually.

### Option 1: One-Click Startup Script (Recommended)
This script will automatically detect and activate your virtual environment (if it exists), install/update packages from `requirements.txt`, and start the app:
```bash
bash run.sh
```

### Option 2: Manual Startup
If you prefer running the commands step-by-step:
```bash
# 1. Activate the virtual environment
source venv/bin/activate

# 2. Install/update required packages
pip install -r requirements.txt

# 3. Start the application
streamlit run app.py
```

---

## 🔑 Security & Configuration

### 1. Browser Login PIN
The dashboard is locked with a 6-digit security PIN: **`124816`**. Entering the PIN authenticates your session for **24 hours** using browser cookies.

### 2. Google Drive Storage
To sync your transaction records securely in the cloud:
- Share your Google Drive data folder with the Service Account email: `gdrive@zenfinance369.iam.gserviceaccount.com` (Grant **Editor** permissions).
- Save your service account JSON file as `gcp_credentials.json` in the root of this project (for local development).
- For cloud deployment (e.g. Streamlit Community Cloud), add the credentials and your Folder ID to your app **Secrets** in TOML format:
  ```toml
  gdrive_folder_id = "17DC3eOMWSWshibk5SbXq33tsnSY7c9HL"

  [gcp_service_account]
  type = "service_account"
  project_id = "zenfinance369"
  private_key_id = "7f6d1a2561500e605614f7ebfab62afd7491e18d"
  private_key = """-----BEGIN PRIVATE KEY-----
  MIIEugIBADANBgkqhkiG9w0BAQEFAASCBKQwggSgAgEAAoIBAQDEcfKi5MHnaWQ+
  ...
  -----END PRIVATE KEY-----"""
  client_email = "gdrive@zenfinance369.iam.gserviceaccount.com"
  client_id = "109621681653665365261"
  auth_uri = "https://accounts.google.com/o/oauth2/auth"
  token_uri = "https://oauth2.googleapis.com/token"
  auth_provider_x509_cert_url = "https://www.googleapis.com/oauth2/v1/certs"
  client_x509_cert_url = "https://www.googleapis.com/robot/v1/metadata/x509/gdrive%40zenfinance369.iam.gserviceaccount.com"
  universe_domain = "googleapis.com"
  ```
