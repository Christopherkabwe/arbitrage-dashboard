import os
import requests
from dotenv import load_dotenv

# Load variables from .env file
load_dotenv()

API_TOKEN = os.getenv("RENDER_API_TOKEN")
SERVICE_ID = os.getenv("RENDER_SERVICE_ID")

HEADERS = {
    "Authorization": f"Bearer {API_TOKEN}",
    "Accept": "application/json",
    "Content-Type": "application/json"
}

def restart_render_service(service_id):
    url = f"https://api.render.com/v1/services/{service_id}/restart"

    response = requests.post(url, headers=HEADERS)
    
    if response.status_code == 200:
        print("✅ Service restart initiated successfully.")
    else:
        print(f"❌ Failed to restart service. Status code: {response.status_code}")
        print(response.text)

if __name__ == "__main__":
    restart_render_service(SERVICE_ID)
