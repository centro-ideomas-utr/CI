import os
from google_auth_oauthlib.flow import InstalledAppFlow
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
SCOPES = ['https://www.googleapis.com/auth/drive']

def autenticar_drive():
    creds = None
    if os.path.exists('token.json'):
        try:
            creds = Credentials.from_authorized_user_file('token.json', SCOPES)
        except Exception:
            print("El token existente es inválido, se eliminará.")
            os.remove('token.json')
            creds = None
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                print("Intentando refrescar el token...")
                creds.refresh(Request())
            except Exception as e:
                print(f"Error al refrescar: {e}. Se requiere nueva autorización.")
                creds = None
        
        if not creds:
            print("Iniciando nuevo flujo de autorización...")
            # Asegúrate de tener tu archivo credentials.json en la misma carpeta
            if not os.path.exists('client_secret.json'):
                print("ERROR: No se encontró el archivo 'credentials.json'. Descárgalo de Google Cloud Console.")
                return

            flow = InstalledAppFlow.from_client_secrets_file(
                'client_secret.json', SCOPES)
            creds = flow.run_local_server(port=0)
        
        # Guarda las credenciales para la próxima ejecución
        with open('token.json', 'w') as token:
            token.write(creds.to_json())
            print("¡Éxito! Nuevo archivo token.json generado correctamente.")

if __name__ == '__main__':
    autenticar_drive()