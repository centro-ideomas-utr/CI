from flask import Flask, render_template, request, abort, redirect, url_for, Response, jsonify, session
import yagmail
import mysql.connector
from pymongo import MongoClient
from bson import ObjectId
from datetime import datetime, timedelta, date
import os
import uuid
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename
import json
from dotenv import load_dotenv
import secrets
import string
import decimal
import threading
from io import BytesIO 
from gridfs import GridFS
import locale
from io import BytesIO 
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

load_dotenv()

app = Flask(__name__)

app.config['SECRET_KEY'] = os.getenv('SECRET_KEY')
if not app.config['SECRET_KEY']:
    raise ValueError("No se encontró SECRET_KEY. Define la variable de entorno.")

def format_currency_mxn(value):
    if value is None:
        return "0.00"
    try:
        return f"{float(value):,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")
    except (TypeError, ValueError):
        return str(value)

app.jinja_env.filters['format_currency'] = format_currency_mxn

@app.context_processor
def inject_now():
    return {'now': datetime.utcnow()}
try:
    YAG_USER = os.getenv('YAG_USER')
    YAG_TOKEN = os.getenv('YAG_TOKEN')
    
    if not YAG_USER or not YAG_TOKEN:
        print("Advertencia: Credenciales de Yagmail no encontradas. El envío de correos estará deshabilitado.")
        yag = None
    else:
        yag = yagmail.SMTP(YAG_USER, YAG_TOKEN)
except Exception as e:
    print(f"Error al inicializar yagmail: {e}")
    yag = None

db_config = {
    "host": os.getenv('DB_HOST'),
    "user": os.getenv('DB_USER'),
    "password": os.getenv('DB_PASSWORD'),
    "database": os.getenv('DB_DATABASE')
}

MONGO_URI = os.getenv('MONGO_URI')
if not MONGO_URI:
    raise ValueError("No se encontró MONGO_URI. Define la variable de entorno.")
mongo_client = MongoClient(MONGO_URI)
mongo_db = mongo_client["ci_prueba"]
expedientes_col = mongo_db["expedientes"]
logs_col = mongo_db["logs"]
fs = GridFS(mongo_db) 

global_avisos = []

FACTURAMA_USER = 'CentrodeIdiomasUTR'
FACTURAMA_PASSWORD = 'Uli0514122324#'
FACTURAMA_URL = 'https://dev.facturama.mx/Profile/TaxProfile'

TOKEN_FILE = 'token.json' 
DRIVE_FOLDER_ID = '12j--_cyQEduhsfmePTOQuzou0_yUlSdM'

def crear_carpeta_drive(nombre_carpeta):
    """Crea una carpeta específica para el usuario dentro de tu carpeta principal."""
    try:
        if os.path.exists(TOKEN_FILE):
            creds = Credentials.from_authorized_user_file(TOKEN_FILE, ['https://www.googleapis.com/auth/drive'])
        else:
            return None

        service = build('drive', 'v3', credentials=creds)
        
        file_metadata = {
            'name': nombre_carpeta,
            'mimeType': 'application/vnd.google-apps.folder',
            'parents': [DRIVE_FOLDER_ID] # Se crea DENTRO de tu carpeta principal
        }
        
        file = service.files().create(body=file_metadata, fields='id').execute()
        return file.get('id') # Retorna el ID de la nueva carpeta personal
    except Exception as e:
        print(f"Error creando carpeta en Drive: {e}")
        return None

def subir_a_drive(file_stream, filename, mimetype, folder_id=None):
    """
    Sube archivo a Google Drive.
    AHORA ACEPTA 'folder_id' para guardarlo en la carpeta específica de la persona.
    """
    try:
        if os.path.exists(TOKEN_FILE):
            creds = Credentials.from_authorized_user_file(TOKEN_FILE, ['https://www.googleapis.com/auth/drive'])
        else:
            return None

        service = build('drive', 'v3', credentials=creds)

        destino = folder_id if folder_id else DRIVE_FOLDER_ID

        file_metadata = {
            'name': filename,
            'parents': [destino] 
        }
        
        media = MediaIoBaseUpload(file_stream, mimetype=mimetype, resumable=True)
        
        file = service.files().create(
            body=file_metadata,
            media_body=media,
            fields='id, webViewLink'
        ).execute()
        
        # Permiso público de lectura (Opcional)
        permission = {'type': 'anyone', 'role': 'reader'}
        service.permissions().create(fileId=file.get('id'), body=permission).execute()

        return file.get('webViewLink')
    except Exception as e:
        print(f"Error subiendo a Drive: {e}")
        return None

def eliminar_recurso_drive(file_id):
    """Borra un archivo o una carpeta entera de Drive."""
    try:
        if os.path.exists(TOKEN_FILE):
            creds = Credentials.from_authorized_user_file(TOKEN_FILE, ['https://www.googleapis.com/auth/drive'])
        else:
            return False

        service = build('drive', 'v3', credentials=creds)
        service.files().delete(fileId=file_id).execute()
        print(f"Recurso Drive {file_id} eliminado.")
        return True
    except Exception as e:
        print(f"No se pudo eliminar de Drive (quizás ya no existe): {e}")
        return False

VALOR_HORA = 105.00
COSTO_REINSCRIPCION_BASE = 1870.00

def calcular_impuestos(horas_trabajadas):
    subtotal = horas_trabajadas * VALOR_HORA
    
    # Impuestos Trasladados (IVA 16%)
    tasa_iva = 0.16
    iva_trasladado = round(subtotal * tasa_iva, 2)
    
    # Retenciones (ISR Retenido 1.25% para RESICO PF)
    tasa_isr_retenido = 0.0125
    isr_retenido = round(subtotal * tasa_isr_retenido, 2)
    
    # Total Neto a pagar (Subtotal + IVA - Retención)
    total_neto = round(subtotal + iva_trasladado - isr_retenido, 2)
    
    return {
        "subtotal": subtotal,
        "iva_trasladado": iva_trasladado,
        "isr_retenido": isr_retenido,
        "total_neto": total_neto,
        "horas": horas_trabajadas
    }

def parse_enum(row):
    """Función para extraer valores de un ENUM de MySQL."""
    if not row or "Type" not in row:
        return []
    return row["Type"].replace("enum(", "").replace(")", "").replace("'", "").split(",")

# -------------------------------------------------------------
# FUNCIÓN ASÍNCRONA PARA REGISTRO DE PERSONAL
# -------------------------------------------------------------

def process_personal_registration_async(id_personal, tipo_personal, email, contrasena_temporal, uploaded_files_data, nombre, apellido_p, apellido_m, portal_url_lista):
    print(f"INICIANDO HILO: Creando carpeta y subiendo archivos para {email}")
    
    conn_async = None
    cursor_async = None
    yag_async = None
    
    # Configurar correo
    try:
        YAG_USER = os.getenv('YAG_USER')
        YAG_TOKEN = os.getenv('YAG_TOKEN')
        if YAG_USER and YAG_TOKEN:
            yag_async = yagmail.SMTP(YAG_USER, YAG_TOKEN)
    except Exception:
        yag_async = None
    
    try:
        # 1. CREAR CARPETA EN DRIVE PARA LA PERSONA
        nombre_completo_carpeta = f"{nombre} {apellido_p} {apellido_m} - {tipo_personal.upper()}"
        user_folder_id = crear_carpeta_drive(nombre_completo_carpeta)
        
        if user_folder_id:
            print(f"Carpeta creada en Drive: {nombre_completo_carpeta}")
        else:
            print("Falló creación de carpeta, se usarán la raíz.")
            user_folder_id = None # Se guardará en la carpeta general si falla

        # 2. SUBIR ARCHIVOS A ESA CARPETA
        documentos_mongo = {}
        
        for mongo_key, file_content, original_filename, content_type in uploaded_files_data:
            file_stream = BytesIO(file_content) 
            
            # Pasamos el ID de su carpeta personal
            drive_link = subir_a_drive(file_stream, original_filename, content_type, folder_id=user_folder_id)
            
            if drive_link:
                documentos_mongo[mongo_key] = drive_link
            else:
                documentos_mongo[mongo_key] = None

        # 3. GUARDAR EN MONGODB (Incluyendo el ID de la carpeta para borrarla luego)
        expediente_doc = {
            "tipo": tipo_personal, 
            "id_relacional": id_personal,
            "documentos": documentos_mongo, 
            "drive_folder_id": user_folder_id,  # <--- GUARDAMOS ESTO IMPORTANTE
            "metadata": { "fecha_subida": datetime.utcnow(), "actualizado_por": "sistema_admin_async" }
        }
        mongo_id = expedientes_col.insert_one(expediente_doc).inserted_id
        
        # 4. ACTUALIZAR MYSQL
        conn_async = mysql.connector.connect(**db_config)
        cursor_async = conn_async.cursor()
        
        table_name = "profesores" if tipo_personal == 'maestro' else "staff"
        id_column = "id_profesor" if tipo_personal == 'maestro' else "id_staff"
        
        update_query = f"UPDATE {table_name} SET id_expediente_mongo = %s WHERE {id_column} = %s"
        cursor_async.execute(update_query, (str(mongo_id), id_personal))
        conn_async.commit()
        
        # 5. ENVIAR CORREO (Igual que antes)
        if yag_async:
            nombre_completo = f"{nombre} {apellido_p} {apellido_m}".strip()
            subject = f"¡Bienvenido/a {nombre} al Centro de Idiomas UTR!"
            html_body = f"""
                <html>
                <body style="font-family: Arial, sans-serif;">
                    <div style="padding: 20px; border: 1px solid #ddd;">
                        <h2 style="color: #007bff;">¡Bienvenido/a {nombre_completo}!</h2>
                        <p>Tu expediente digital ha sido creado exitosamente.</p>
                        <p><strong>Usuario:</strong> {email}</p>
                        <p><strong>Contraseña:</strong> {contrasena_temporal}</p>
                        <p><a href="{portal_url_lista}">Acceder al Portal</a></p>
                    </div>
                </body>
                </html>
            """
            yag_async.send(to=email, subject=subject, contents=[html_body])
            
        print("✅ Proceso finalizado con éxito.")
        
    except Exception as e:
        print(f"❌ Error en hilo: {e}")
        if conn_async: conn_async.rollback()
    finally:
        if cursor_async: cursor_async.close()
        if conn_async and conn_async.is_connected(): conn_async.close()

@app.route('/expediente/ver/<string:mongo_id>/<string:tipo_doc>')
def ver_documento_expediente(mongo_id, tipo_doc):
    try:
        expediente = expedientes_col.find_one({"_id": ObjectId(mongo_id)})
        
        if not expediente:
            abort(404, description="Expediente no encontrado.")

        # Obtener la URL guardada (Ahora es un link de Drive)
        url_drive = expediente.get('documentos', {}).get(tipo_doc)
        
        if not url_drive:
            abort(404, description=f"Documento '{tipo_doc}' no encontrado.")

        # REDIRECCIONAR A GOOGLE DRIVE
        return redirect(url_drive)

    except Exception as e:
        print(f"Error al redirigir documento: {e}")
        abort(500, description="Error interno.")

# =================================================================
# === RUTAS DE GESTIÓN DE PERSONAL (Maestros y Staff) ===
# =================================================================

@app.route("/gestion-personal")
def gestion_personal():
    conn = None
    personal = []
    busqueda = request.args.get('q', '').strip() 
    
    try:
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor(dictionary=True)

        where_clause = ""
        search_params_tuple = ()

        if busqueda:
            where_clause = """
                WHERE 
                    (nombre LIKE %s OR apellido_p LIKE %s OR apellido_m LIKE %s OR correo_electronico LIKE %s)
            """
            search_param = f"%{busqueda}%"
            search_params_tuple = (search_param, search_param, search_param, search_param)

        def fetch_personal(table, id_col, tipo):
            query = f"""
                SELECT {id_col} AS id, nombre, apellido_p, apellido_m, genero, '{tipo}' AS tipo 
                FROM {table}
                {where_clause}
            """
            cursor.execute(query, search_params_tuple) 
            return cursor.fetchall()

        maestros = fetch_personal("profesores", "id_profesor", "maestro")
        staff_list = fetch_personal("staff", "id_staff", "staff")
        personal = maestros + staff_list

    except Exception as e:
        print(f"ERROR GENERAL al cargar personal: {e}")
        
    finally:
        if conn and conn.is_connected():
            cursor.close()
            conn.close()

    return render_template("añadiradmin.html", personal=personal, busqueda=busqueda)
    
@app.route('/guardar-personal', methods=['POST'])
def guardar_personal():
    conn = None
    email = request.form.get('email')
    
    # 1. Generar contraseña temporal
    caracteres = string.ascii_letters + string.digits 
    contrasena_temporal = ''.join(secrets.choice(caracteres) for i in range(12))
    password_encriptada = generate_password_hash(contrasena_temporal)
    
    # 2. Obtener datos del formulario
    form_data = {
        'nombre': request.form.get('nombre'),
        'apellidos': request.form.get('apellidos'),
        'email': email,
        'telefono': request.form.get('telefono'),
        'tipo_personal': request.form.get('tipo_personal'),
        'fecha_nacimiento': request.form.get('fecha_n') if request.form.get('fecha_n') else None,
        'genero': request.form.get('genero')
    }
    
    # 3. Procesar archivos (leer contenido para pasarlo al hilo)
    uploaded_files_data = []
    file_mapping = {
        "doc_acta": "acta_nacimiento",
        "doc_identificacion": "identificacion",
        "doc_estado": "estado_de_cuenta",
        "doc_cv": "cv",
        "doc_comprobante_domicilio": "comprobante_domicilio",
        "doc_carta1": "carta_recomendacion1",
        "doc_carta2": "carta_recomendacion2",
        "doc_titulo": "titulo",
        "doc_cedula": "cedula",
        "doc_situacion_fiscal": "constancia_situacion_fiscal",
    }
    
    for form_field, mongo_key in file_mapping.items():
        file = request.files.get(form_field)
        if file and file.filename:
            file_content = file.read() 
            uploaded_files_data.append((mongo_key, file_content, secure_filename(file.filename), file.content_type))
    
    cursor = None
    
    try:
        # 4. Separar apellidos
        apellido_parts = form_data['apellidos'].split(' ')
        apellido_p = apellido_parts[0]
        apellido_m = ' '.join(apellido_parts[1:]) if len(apellido_parts) > 1 else ''

        # 5. Guardar datos básicos en MySQL
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor()

        if form_data['tipo_personal'] == 'maestro':
            table_name = "profesores"
            query = """
                INSERT INTO profesores 
                (nombre, apellido_p, apellido_m, correo_electronico, telefono, fecha_nacimiento, contraseña, genero)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """
            params = (form_data['nombre'], apellido_p, apellido_m, email, form_data['telefono'], form_data['fecha_nacimiento'], password_encriptada, form_data['genero'])
        
        elif form_data['tipo_personal'] == 'staff':
            table_name = "staff"
            query = """
                INSERT INTO staff 
                (nombre, apellido_p, apellido_m, correo_electronico, telefono, fecha_nacimiento, contraseña, genero)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """
            params = (form_data['nombre'], apellido_p, apellido_m, email, form_data['telefono'], form_data['fecha_nacimiento'], password_encriptada, form_data['genero'])
        else:
            return jsonify({'status': 'error', 'message': 'Error: Tipo de personal no válido.'}), 400

        cursor.execute(query, params)
        id_personal = cursor.lastrowid
        conn.commit()
        
        portal_url_pregenerada = url_for('login', _external=True)

        thread = threading.Thread(
            target=process_personal_registration_async, 
            args=(
                id_personal, 
                form_data['tipo_personal'],
                email, 
                contrasena_temporal, 
                uploaded_files_data, 
                form_data['nombre'],
                apellido_p,
                apellido_m,
                portal_url_pregenerada
            )
        )
        thread.start()

        return jsonify({'status': 'success', 'message': f'¡{form_data["tipo_personal"].capitalize()} creado. Procesando archivos en segundo plano.'}), 202

    except mysql.connector.Error as err:
        if conn: conn.rollback()
        error_msg = f'Error en base de datos: {err}'
        status_code = 500
        if err.errno == 1062:
            error_msg = f'Error: El correo electrónico "{email}" ya está registrado.'
            status_code = 400
        return jsonify({'status': 'error', 'message': error_msg}), status_code
        
    except Exception as e:
        if conn: conn.rollback()
        return jsonify({'status': 'error', 'message': f'Error en el servidor: {e}'}), 500
    finally:
        if 'cursor' in locals() and cursor: cursor.close()
        if conn and conn.is_connected(): conn.close()
        
@app.route("/editar-personal/<string:tipo>/<int:id>", methods=['POST'])
def editar_personal(tipo, id):
    conn = None
    if request.method != 'POST':
        return redirect(url_for('maestroinfo', tipo=tipo, id=id))

    try:
        if tipo not in ['maestro', 'staff']:
            return "Error: Tipo de personal no válido.", 400

        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor()
        
        data = request.form
        table_name = "profesores" if tipo == 'maestro' else "staff"
        id_column = "id_profesor" if tipo == 'maestro' else "id_staff"
        
        update_fields = ['nombre', 'apellido_p', 'apellido_m', 'correo_electronico', 'fecha_nacimiento', 'telefono', 'genero']
        personal_updates = []
        personal_values = []
        
        for field in update_fields:
            value = data.get(field)
            if value is not None:
                if field == 'fecha_nacimiento' and value == '':
                    personal_updates.append(f"{field} = NULL")
                else:
                    personal_updates.append(f"{field} = %s")
                    personal_values.append(value)
        
        if personal_updates:
            query_personal = f"UPDATE {table_name} SET {', '.join(personal_updates)} WHERE {id_column} = %s"
            personal_values.append(id)
            cursor.execute(query_personal, personal_values)
            
        if tipo == 'maestro':
            fiscal_fields = ['rfc', 'razon_social', 'regimen_fiscal', 'cuenta_clabe']
            fiscal_updates = []
            fiscal_values = []
            
            cursor.execute("SELECT id_profesor FROM profesores_datos_fiscales WHERE id_profesor = %s", (id,))
            exists = cursor.fetchone()
            
            for field in fiscal_fields:
                value = data.get(field)
                if value is not None:
                    fiscal_updates.append(f"{field} = %s")
                    fiscal_values.append(value)

            if fiscal_updates:
                if exists:
                    query_fiscal = f"UPDATE profesores_datos_fiscales SET {', '.join(fiscal_updates)} WHERE id_profesor = %s"
                    fiscal_values.append(id)
                    cursor.execute(query_fiscal, fiscal_values)
                else:
                    fiscal_fields_str = ', '.join(['id_profesor'] + fiscal_fields)
                    placeholders = ', '.join(['%s'] * (len(fiscal_fields) + 1))
                    query_fiscal_insert = f"INSERT INTO profesores_datos_fiscales ({fiscal_fields_str}) VALUES ({placeholders})"
                    fiscal_values_insert = [id] + fiscal_values
                    cursor.execute(query_fiscal_insert, fiscal_values_insert)

        conn.commit()
        
    except Exception as e:
        conn.rollback()
        return "Error al guardar los cambios: " + str(e), 500
        
    finally:
        if conn and conn.is_connected():
            cursor.close()
            conn.close()

    return redirect(url_for('maestroinfo', tipo=tipo, id=id))

@app.route('/eliminar-personal/<string:tipo>/<int:id_relacional>', methods=['POST'])
def eliminar_personal(tipo, id_relacional):
    conn = None
    try:
        if tipo not in ['maestro', 'staff']:
            return jsonify({'status': 'error', 'message': 'Tipo no válido.'}), 400

        table_name = "profesores" if tipo == 'maestro' else "staff"
        id_column = "id_profesor" if tipo == 'maestro' else "id_staff"
        
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor()

        cursor.execute(f"SELECT id_expediente_mongo FROM {table_name} WHERE {id_column} = %s", (id_relacional,))
        mongo_id_tuple = cursor.fetchone()
        mongo_id = mongo_id_tuple[0] if mongo_id_tuple else None

        cursor.execute(f"DELETE FROM {table_name} WHERE {id_column} = %s", (id_relacional,))
        
        if cursor.rowcount == 0:
            conn.rollback()
            return jsonify({'status': 'error', 'message': f'No se encontró {tipo}.'}), 404

        if mongo_id:
            expediente = expedientes_col.find_one({"_id": ObjectId(mongo_id)})
            
            if expediente and 'drive_folder_id' in expediente:
                folder_id = expediente['drive_folder_id']
                if folder_id:
                    eliminar_recurso_drive(folder_id)
            
            expedientes_col.delete_one({"_id": ObjectId(mongo_id)})
        
        conn.commit()
        return jsonify({'status': 'success', 'message': f'{tipo.capitalize()} y sus documentos eliminados correctamente.'})

    except Exception as e:
        if conn: conn.rollback()
        if isinstance(e, mysql.connector.Error) and e.errno == 1451:
             return jsonify({'status': 'error', 'message': "No se puede eliminar: tiene dependencias (grupos, etc)."}), 400
        return jsonify({'status': 'error', 'message': f'Error: {e}'}), 500
    finally:
        if conn and conn.is_connected():
            cursor.close()
            conn.close()

# =================================================================
# === RUTAS DE RESTABLECIMIENTO DE CONTRASEÑA ===
# =================================================================

@app.route('/solicitar-restablecimiento', methods=['GET', 'POST'])
def solicitar_restablecimiento():
    """Muestra el formulario para solicitar el correo o envía el enlace."""
    if request.method == 'GET':
        return render_template('solicitar_restablecimiento.html') 
    
    email = request.form.get('correo_electronico')
    conn = None
    
    try:
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor()
        
        # 1. Buscar el usuario en ambas tablas (Staff y Profesores)
        table_name = None
        
        cursor.execute("SELECT id_profesor FROM profesores WHERE correo_electronico = %s", (email,))
        if cursor.fetchone():
            table_name = "profesores"
        else:
            cursor.execute("SELECT id_staff FROM staff WHERE correo_electronico = %s", (email,))
            if cursor.fetchone():
                table_name = "staff"
        
        if not table_name:
            # Mensaje genérico para no revelar si el correo existe
            return render_template('solicitar_restablecimiento.html',
                                    message="Si el correo existe en nuestro sistema, se ha enviado un enlace.")

        reset_token = secrets.token_urlsafe(32)
        expiration = datetime.now() + timedelta(hours=1)
        
        query = f"""
            UPDATE {table_name} 
            SET reset_token = %s, token_expiration = %s 
            WHERE correo_electronico = %s
        """
        cursor.execute(query, (reset_token, expiration, email))
        conn.commit()

        if yag:
            reset_url = url_for('restablecer_contrasena', token=reset_token, _external=True)
            subject = "Solicitud de Restablecimiento de Contraseña UTR"
            contents = [
                "<p>Hemos recibido una solicitud para restablecer la contraseña de tu cuenta.</p>",
                f"<p>Haz clic en el siguiente enlace para continuar:</p>",
                f"<p><a href='{reset_url}'>Restablecer Contraseña Ahora</a></p>",
                "<p>Este enlace caducará en 1 hora. Si no solicitaste este cambio, por favor ignora este correo.</p>"
            ]
            yag.send(to=email, subject=subject, contents=contents)

        return render_template('solicitar_restablecimiento.html', 
                                message="Si el correo existe en nuestro sistema, se ha enviado un enlace para restablecer la contraseña.")
        
    except Exception as e:
        print(f"Error en solicitud de restablecimiento: {e}")
        return render_template('solicitar_restablecimiento.html', 
                                error="Error interno del servidor. Intente más tarde.")
    finally:
        if conn and conn.is_connected():
            cursor.close()
            conn.close()

@app.route('/restablecer-contrasena/<token>', methods=['GET', 'POST'])
def restablecer_contrasena(token):
    """Verifica el token y permite al usuario establecer una nueva contraseña."""
    conn = None
    try:
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor(dictionary=True)
        
        # 1. Buscar usuario por token en ambas tablas
        user_data = None
        table_name = None
        id_column = None
        
        # Intentar buscar en profesores
        cursor.execute("SELECT id_profesor AS id, reset_token, token_expiration FROM profesores WHERE reset_token = %s", (token,))
        user_data = cursor.fetchone()
        if user_data:
            table_name = "profesores"
            id_column = "id_profesor"
        
        # Si no está en profesores, buscar en staff
        if not user_data:
            cursor.execute("SELECT id_staff AS id, reset_token, token_expiration FROM staff WHERE reset_token = %s", (token,))
            user_data = cursor.fetchone()
            if user_data:
                table_name = "staff"
                id_column = "id_staff"

        # 2. Validar token y expiración
        if not user_data or user_data['token_expiration'] < datetime.now():
            return render_template('form_restablecer.html', 
                                    error="El enlace de restablecimiento es inválido o ha expirado.", 
                                    token=token)

        if request.method == 'GET':
            # Muestra el formulario de cambio de contraseña
            return render_template('form_restablecer.html', token=token)

        # Si es POST, procesar nueva contraseña
        nueva_contrasena = request.form.get('nueva_contrasena')
        confirmar_contrasena = request.form.get('confirmar_contrasena')
        
        if not nueva_contrasena or nueva_contrasena != confirmar_contrasena or len(nueva_contrasena) < 8:
            return render_template('form_restablecer.html', 
                                    error="Las contraseñas no coinciden o no cumplen con la longitud mínima (8 caracteres).", 
                                    token=token)

        hashed_password = generate_password_hash(nueva_contrasena)
        
        # 3. Actualizar contraseña y limpiar token
        query = f"""
            UPDATE {table_name} 
            SET contraseña = %s, reset_token = NULL, token_expiration = NULL 
            WHERE {id_column} = %s
        """
        cursor.execute(query, (hashed_password, user_data['id']))
        conn.commit()

        # Redirigir al login con mensaje de éxito
        return redirect(url_for('login', message="Contraseña restablecida con éxito. Ya puede iniciar sesión."))
        
    except Exception as e:
        print(f"Error en restablecimiento de contraseña: {e}")
        return render_template('form_restablecer.html', 
                                error="Error interno del servidor al procesar el cambio.", 
                                token=token)
    finally:
        if conn and conn.is_connected():
            cursor.close()
            conn.close()

# =================================================================
# === RUTAS ACADÉMICAS Y DE ALUMNOS ===
# =================================================================

@app.route("/")
def inicio():
    return render_template("index.html")

@app.route("/registro")
def registro():
    conn = None
    try:
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SHOW COLUMNS FROM alumnos LIKE 'genero'")
        genero = parse_enum(cursor.fetchone())
        cursor.execute("SHOW COLUMNS FROM alumnos LIKE 'tipo_inscripcion'")
        tipodeinscripcion = parse_enum(cursor.fetchone())
        cursor.execute("SELECT id_idioma, nombre FROM idioma ORDER BY nombre")
        idiomas = cursor.fetchall()
        query_horarios = "SELECT id_horario, CONCAT(dias, ' - ', hora, ' (', sede, ')') AS detalle FROM horario ORDER BY dias, hora"
        cursor.execute(query_horarios)
        horarios = cursor.fetchall()
    except mysql.connector.Error as err:
        genero, tipodeinscripcion, idiomas, horarios = [], [], [], []
    finally:
        if 'conn' in locals() and conn and conn.is_connected():
            cursor.close()
            conn.close()

    return render_template("registro.html", genero=genero, tipodeinscripcion=tipodeinscripcion, idiomas=idiomas, horarios=horarios)

@app.route("/guardar", methods=["POST"])
def guardar():
    conn = None
    cursor = None
    try:
        datos = {
            "correo": request.form["correo_electronico"],
            "nombre": request.form["nombre"],
            "apellido_p": request.form["apellido_p"],
            "apellido_m": request.form["apellido_m"],
            "telefono": request.form["telefono"],
            "fecha_nacimiento": datetime.strptime(request.form["fecha_nacimiento"], "%Y-%m-%d").date(),
            "domicilio": request.form["domicilio"],
            "genero": request.form["genero"],
            "tipo_inscripcion": request.form["tipo_inscripcion"],
        }
        
        idiomas_seleccionados = request.form.getlist('idiomas[]')
        horarios_seleccionados = request.form.getlist('horarios[]')
        inscripciones_validas = list(zip(idiomas_seleccionados, horarios_seleccionados))
        inscripciones_validas = [(i, h) for i, h in inscripciones_validas if i and h]
        
        if not inscripciones_validas:
             return "<h1>Error: Debe seleccionar al menos un idioma y su horario correspondiente.</h1><a href='/registro'>Volver</a>", 400

        # --- Lógica de Manejo de Archivos (GOOGLE DRIVE) ---
        file_fields = {
            "acta_n": "acta_nacimiento",
            "identificacion": "identificacion",
            "formato_descuento": "formato_descuento",
            "documentos_comprobatorios": "documentos_comprobatorios",
        }
        
        documentos_mongo = {}
        
        for form_field, mongo_key in file_fields.items():
            file = request.files.get(form_field) 
            if file and file.filename:
                original_filename_secure = secure_filename(file.filename)
                
                # Leemos archivo y lo convertimos a Stream
                file_content = file.read()
                file_stream = BytesIO(file_content)

                # SUBIR A DRIVE
                drive_link = subir_a_drive(file_stream, original_filename_secure, file.content_type)
                
                documentos_mongo[mongo_key] = drive_link # Guardamos URL
            else:
                documentos_mongo[mongo_key] = None

        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor()
        
        cursor.execute("SELECT COALESCE(MAX(matricula),16446)+1 FROM alumnos")
        matricula = cursor.fetchone()[0]

        cursor.execute("""
            INSERT INTO alumnos 
            (matricula, nombre, apellido_p, apellido_m, correo_electronico, telefono,
             fecha_nacimiento, domicilio, genero, tipo_inscripcion)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """, (matricula, datos["nombre"], datos["apellido_p"], datos["apellido_m"], datos["correo"],
            datos["telefono"], datos["fecha_nacimiento"], datos["domicilio"], datos["genero"],
            datos["tipo_inscripcion"]))

        id_alumno = cursor.lastrowid
        
        inscripcion_query = """
            INSERT INTO inscripciones_idioma (id_alumno, id_idioma, id_horario)
            VALUES (%s, %s, %s) ON DUPLICATE KEY UPDATE id_alumno = id_alumno;
        """
        for id_idioma, id_horario in inscripciones_validas:
            cursor.execute(inscripcion_query, (id_alumno, int(id_idioma), int(id_horario)))

        # Guardar Expediente en MongoDB (URLS de Drive)
        expediente_doc = {
            "tipo": "alumno",
            "id_relacional": id_alumno,
            "documentos": documentos_mongo, 
            "metadata": { "fecha_subida": datetime.utcnow(), "actualizado_por": "sistema_auto" }
        }
        mongo_id = expedientes_col.insert_one(expediente_doc).inserted_id

        cursor.execute("UPDATE alumnos SET id_expediente_mongo = %s WHERE id_alumno = %s", (str(mongo_id), id_alumno))
        conn.commit()

        logs_col.insert_one({
            "tipo_entidad": "alumno",
            "id_entidad": id_alumno,
            "accion": "registro",
            "detalle": "Alumno registrado con Docs en Drive.",
            "fecha": datetime.utcnow()
        })

        return render_template("registro_exitoso.html", matricula=matricula)

    except Exception as e:
        if conn and conn.is_connected(): conn.rollback() 
        return f"<h1>Error en el registro: {e}</h1><a href='/registro'>Volver</a>", 500

    finally:
        if cursor: cursor.close()
        if conn and conn.is_connected(): conn.close()

@app.route("/login", methods=["GET", "POST"])
def login():
    # Si ya está logueado, lo redirigimos directamente sin pedir contraseña
    if 'user_id' in session:
        return redirigir_por_rol(session['rol'], session['user_id'])

    if request.method == "GET":
        return render_template("login.html")

    correo = request.form.get("correo_electronico")
    contrasena = request.form.get("contraseña")

    conn = None
    cursor = None
    
    try:
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor(dictionary=True)
        busqueda_usuarios = [
            {"tabla": "staff",      "id_col": "id_staff",    "rol": "staff"},
            {"tabla": "profesores", "id_col": "id_profesor", "rol": "maestro"},
            {"tabla": "alumnos",    "id_col": "id_alumno",   "rol": "alumno"}
        ]

        usuario_encontrado = None
        datos_usuario = None

        for tipo in busqueda_usuarios:
            query = f"""
                SELECT {tipo['id_col']} AS id, nombre, apellido_p, contraseña, '{tipo['rol']}' as rol_detectado
                FROM {tipo['tabla']} 
                WHERE correo_electronico = %s
            """
            cursor.execute(query, (correo,))
            datos_usuario = cursor.fetchone()

            if datos_usuario:
                usuario_encontrado = tipo # Guardamos qué tipo de usuario es
                break # ¡Encontramos el correo! Dejamos de buscar

        # 1. Si no existe el correo en ninguna tabla
        if not datos_usuario:
            return render_template("login.html", error="Usuario no encontrado.")

        # 2. Verificar Contraseña (HASH vs TEXTO)
        password_hash = datos_usuario['contraseña']
        
        # IMPORTANTE: check_password_hash compara la contraseña escrita con el hash de la DB
        if password_hash and check_password_hash(password_hash, contrasena):
            
            # --- CREAR SESIÓN (Esto mantiene al usuario conectado) ---
            session.clear() # Limpiar sesiones anteriores por seguridad
            session['user_id'] = datos_usuario['id']
            session['rol'] = datos_usuario['rol_detectado']
            session['nombre'] = f"{datos_usuario['nombre']} {datos_usuario['apellido_p']}"
            
            print(f" Login exitoso: {session['nombre']} ({session['rol']})")
            
            # Redirigir según quién sea
            return redirigir_por_rol(session['rol'], session['user_id'])
        else:
            print(f"Contraseña incorrecta para {correo}")
            return render_template("login.html", error="Contraseña incorrecta.")

    except Exception as e:
        print(f"Error en login: {e}")
        return render_template("login.html", error="Error interno del servidor.")
    finally:
        if cursor: cursor.close()
        if conn: conn.close()

# Función auxiliar para direccionar (puedes ajustar las rutas aquí)
def redirigir_por_rol(rol, id_usuario):
    if rol == 'staff':
        return redirect(url_for('gestion_personal')) # O 'inicio_staff'
    elif rol == 'maestro':
        return redirect(url_for('portal_facturacion', id_profesor=id_usuario))
    elif rol == 'alumno':
        return redirect(url_for('tablero')) # O 'cursos'
    else:
        return redirect(url_for('inicio'))

@app.route("/historial")
def historial():
    return render_template("historial.html")

@app.route("/asistencias_estudiantes")
def listas():
    return render_template("asistenciasestudiantes.html")

@app.route("/avisos")
def avisos():
    #avisos_publicados = cargar_avisos_desde_db()
    
    # Para FullCalendar: solo eventos con fecha
    calendar_events = [
        {
            #'title': a['title'],
            #'start': a['start'],
            'backgroundColor': '#566a93',
            'borderColor': '#566a93',
            'display': 'dot'
        }
        #for a in avisos_publicados if a['start']
    ]

    return render_template(
        "avisos.html",  # tu archivo HTML que ya tienes
        #avisos_publicados=avisos_publicados,
        calendar_events=calendar_events
    )


# ========================================
# RUTA: PUBLICAR NUEVO AVISO (SIN LOGIN OBLIGATORIO)
# ========================================
@app.route('/aviso', methods=['POST'])
def aviso():
    conn = None
    try:
        mensaje = request.form.get('mensaje', '').strip()
        fecha_evento = request.form.get('fecha_evento')
        id_grupo = request.form.get('id_grupo', 1)

        if not mensaje:
            return "El mensaje es obligatorio", 400

        id_profesor = session.get('user_id') or 1

        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor()

        query = """
            INSERT INTO avisos (descripcion, fecha_calendario, id_profesor, id_grupo)
            VALUES (%s, %s, %s, %s)
        """
        cursor.execute(query, (mensaje, fecha_evento or None, id_profesor, id_grupo))
        conn.commit()

        return redirect(url_for('avisos'))

    except Exception as e:
        if conn:
            conn.rollback()
        print("Error al publicar aviso:", e)
        return "Error al guardar el aviso", 500

    finally:
        if conn and conn.is_connected():
            if 'cursor' in locals():
                cursor.close()
            conn.close()

@app.route("/calificacion")
def calificacion():
    id_grupo = request.args.get('id_grupo')
    conn = None
    info_grupo = None
    try:
        if id_grupo:
            conn = mysql.connector.connect(**db_config)
            cursor = conn.cursor(dictionary=True)
            cursor.execute("""
                SELECT g.grupo, g.numero_salon, 
                       CONCAT(p.nombre, ' ', p.apellido_p) as profe_nombre, 
                       i.nombre as idioma, c.nivel
                FROM grupos g
                LEFT JOIN profesores p ON g.id_profesor = p.id_profesor
                LEFT JOIN cursos c ON g.id_curso = c.id_curso
                LEFT JOIN idioma i ON c.id_idioma = i.id_idioma
                WHERE g.id_grupo = %s
            """, (id_grupo,))
            info_grupo = cursor.fetchone()
    except Exception as e:
        print(e)
    finally:
        if conn: conn.close()
    return render_template("calificacion.html", id_grupo=id_grupo, grupo=info_grupo)

@app.route("/api/obtener_calificaciones", methods=["POST"])
def api_obtener_calificaciones():
    conn = None
    try:
        data = request.get_json()
        id_grupo = data.get('id_grupo')
        parcial = data.get('parcial')
        
        print(f"--- DEBUG API ---")
        print(f"Solicitando Grupo: {id_grupo}, Parcial: {parcial}")

        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor(dictionary=True)

        # 1. Info del Grupo
        cursor.execute("""
            SELECT g.grupo, i.nombre as idioma 
            FROM grupos g 
            JOIN cursos c ON g.id_curso = c.id_curso 
            JOIN idioma i ON c.id_idioma = i.id_idioma 
            WHERE g.id_grupo = %s
        """, (id_grupo,))
        info = cursor.fetchone()
        
        if not info: return jsonify({'status': 'error', 'message': 'Grupo no encontrado'}), 404

        # Determinar tabla
        tabla_calif = "calificaciones_adult"
        if 'Niños' in info['grupo']: tabla_calif = "calificaciones_ninos"
        elif 'LSM' in info['idioma']: tabla_calif = "calificaciones_lsm"

        print(f"Consultando tabla: {tabla_calif}")

        # 2. Consulta SQL
        query = f"""
            SELECT 
                a.id_alumno, a.nombre, a.apellido_p, a.matricula,
                c.* FROM inscripciones_idioma ii
            JOIN alumnos a ON ii.id_alumno = a.id_alumno
            LEFT JOIN {tabla_calif} c 
                ON ii.id_alumno = c.id_alumno 
                AND c.id_grupo = ii.id_grupo 
                AND c.parcial = %s
            WHERE ii.id_grupo = %s
            ORDER BY a.apellido_p ASC
        """
        
        cursor.execute(query, (parcial, id_grupo))
        alumnos_con_notas = cursor.fetchall()

        print(f"Registros en Python: {len(alumnos_con_notas)}")

        # 3. LIMPIEZA PROFUNDA DE DATOS (Nuclear Option)
        # Esto convierte Decimal, Date, Timedelta, etc. a string para que no falle nunca.
        def serializador_seguro(obj):
            if isinstance(obj, (datetime, date)):
                return obj.isoformat()
            if isinstance(obj, decimal.Decimal):
                return float(obj)
            if isinstance(obj, timedelta):
                return str(obj)
            return str(obj)

        # Usamos json.dumps primero para asegurar la conversión
        data_str = json.dumps(alumnos_con_notas, default=serializador_seguro)
        data_clean = json.loads(data_str)

        return jsonify({'status': 'success', 'data': data_clean})

    except Exception as e:
        print(f"ERROR FATAL EN API: {e}")
        import traceback
        traceback.print_exc() # Esto imprimirá el error exacto en tu terminal negra
        return jsonify({'status': 'error', 'message': str(e)}), 500
    finally:
        if conn: conn.close()

@app.route("/api/guardar_calificaciones", methods=["POST"])
def api_guardar_calificaciones():
    conn = None
    try:
        # 1. Recibir datos del Frontend
        data = request.get_json()
        id_grupo = data.get('id_grupo')
        parcial = data.get('parcial')
        calificaciones = data.get('calificaciones') # Lista de objetos
        tipo_curso = data.get('tipo_curso')
        
        # 2. Seguridad: Verificar sesión del profesor
        id_profesor = session.get('user_id')
        if not id_profesor:
            # Si estás probando sin login, usa: id_profesor = 1
            return jsonify({'status': 'error', 'message': 'Sesión caducada'}), 401

        if not calificaciones: 
            return jsonify({'status': 'error', 'message': 'No se recibieron datos para guardar.'}), 400

        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor()

        # 3. Configuración Dinámica de Tablas y Columnas
        # Deben coincidir EXACTAMENTE con tu base de datos
        if tipo_curso == 'adults':
            tabla = "calificaciones_adult"
            columnas = ["pronunciation", "fluency", "grammar_vocabulary", "performance_skill", 
                        "comprenhension", "main_ideas", "grammar_word_choice", "punctuation_capitalization"]
        elif tipo_curso == 'ninos':
            tabla = "calificaciones_ninos"
            columnas = ["pronunciacion", "fluidez", "gramatica_vocabulario", "habilidades_pronunciacion", 
                        "comprension", "contenido", "organizacion", "lenguaje", "gramatica", "ortografia"]
        elif tipo_curso == 'lsm':
            tabla = "calificaciones_lsm"
            columnas = ["expresiones_faciales", "movimientos_corporales", "movimiento_manos", "identifica_ideograma", 
                        "uos_mano_dominante", "realiza_dactilogía", "transmite_mensaje", "detalles_coordinada", 
                        "orden_secuencial", "percibir_detalles", "comprende_mensaje", "recuerda_senas"]
        else:
            return jsonify({'status': 'error', 'message': 'Tipo de curso no identificado'}), 400

        # 4. Construcción de la Query SQL Dinámica
        # Generamos los placeholders (%s) según la cantidad de columnas
        cols_str = ", ".join(columnas)
        vals_str = ", ".join(["%s"] * len(columnas))
        
        # Parte mágica: Si ya existe, actualiza los valores (ON DUPLICATE KEY UPDATE)
        update_str = ", ".join([f"{c}=VALUES({c})" for c in columnas])

        sql = f"""
            INSERT INTO {tabla} (id_grupo, id_alumno, id_profesor, parcial, {cols_str})
            VALUES (%s, %s, %s, %s, {vals_str})
            ON DUPLICATE KEY UPDATE {update_str}, fecha_registro=NOW()
        """

        # 5. Procesamiento de Datos
        registros_procesados = 0
        
        for calif in calificaciones:
            raw_id = calif.get('id_alumno')
            
            # --- VALIDACIÓN CRÍTICA (Evita error 1366) ---
            if not raw_id or str(raw_id).lower() in ['null', 'undefined', '']:
                continue # Saltamos este registro corrupto
            
            try:
                id_alumno = int(raw_id) # Aseguramos que sea entero
            except ValueError:
                continue # Si no es número, saltar
            # ---------------------------------------------

            # Extraer valores de las columnas
            valores = []
            for col in columnas:
                val = calif.get(col)
                # Si viene vacío, guardamos None (NULL en SQL)
                if val is None or val == "":
                    valores.append(None)
                else:
                    valores.append(val)

            # Armar parámetros: Fijos + Dinámicos
            params = [id_grupo, id_alumno, id_profesor, parcial] + valores
            
            cursor.execute(sql, params)
            registros_procesados += 1

        conn.commit()
        
        return jsonify({
            'status': 'success', 
            'message': f'Se guardaron {registros_procesados} registros del Parcial {parcial}.'
        })

    except Exception as e:
        print(f"ERROR GUARDAR CALIF: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500
    finally:
        if conn: conn.close()

@app.route("/calificaciones") #alumno
def calificaciones():
    return render_template("calificacionesestudiantes.html")

@app.route('/tablero')
def tablero():
    return render_template("tableroestudiantes.html")

@app.route("/evidencias") #maetsro
def evidencias():
    return render_template("evidencias.html")

@app.route("/clasesprofe") #porfe y se queda
def clasesprofe():
    return render_template("clasesprofe.html")

@app.route("/asistencia")
def asistencia():
    return redirect('gestion_asistencia')

@app.route("/gestion_asistencia/<int:id_grupo>")
def gestion_asistencia(id_grupo):
    conn = None
    try:
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor(dictionary=True)
        
        # --- CORRECCIÓN AQUÍ ---
        # Agregamos 'h.dias' y 'h.hora' al SELECT y el JOIN con horario
        cursor.execute("""
            SELECT g.grupo, g.numero_salon, 
                   h.dias, h.hora, 
                   CONCAT(p.nombre, ' ', p.apellido_p) as profe_nombre, 
                   i.nombre as idioma, c.nivel
            FROM grupos g
            LEFT JOIN profesores p ON g.id_profesor = p.id_profesor
            LEFT JOIN cursos c ON g.id_curso = c.id_curso
            LEFT JOIN idioma i ON c.id_idioma = i.id_idioma
            LEFT JOIN horario h ON g.id_horario = h.id_horario  
            WHERE g.id_grupo = %s
        """, (id_grupo,))
        
        info_grupo = cursor.fetchone()

        if not info_grupo:
            return "Grupo no encontrado", 404

        # 2. Obtener alumnos inscritos
        cursor.execute("""
            SELECT a.id_alumno, a.matricula, 
                   CONCAT(a.nombre, ' ', a.apellido_p, ' ', IFNULL(a.apellido_m, '')) as nombre_completo 
            FROM alumnos a
            JOIN inscripciones_idioma ii ON a.id_alumno = ii.id_alumno
            WHERE ii.id_grupo = %s AND ii.estado = 'Activo'
            ORDER BY a.apellido_p ASC
        """, (id_grupo,))
        alumnos = cursor.fetchall()
        
        return render_template("listas.html", 
                             alumnos=alumnos, 
                             grupo=info_grupo, 
                             id_grupo=id_grupo)
        
    except Exception as e:
        print(f"Error: {e}")
        return f"Error de conexión: {e}", 500
    finally:
        if conn and conn.is_connected(): conn.close()

# --- API: GUARDAR ASISTENCIA (Adaptado a tu Schema) ---
@app.route("/api/guardar_asistencia", methods=["POST"])
def api_guardar_asistencia():
    conn = None
    try:
        data = request.get_json()
        
        # Datos recibidos del JS
        id_alumno = data.get('id_alumno')
        id_grupo = data.get('id_grupo')
        fecha_clase = data.get('fecha') # YYYY-MM-DD
        asistio = data.get('asistio')   # true/false
        
        # Valor para tu columna enum/boolean. Tu tabla dice BOOLEAN (0 o 1)
        valor_asistencia = 1 if asistio else 0

        # Necesitamos el id_profesor. Lo ideal es sacarlo de la sesión o del grupo.
        # Aquí lo consultamos rápido basándonos en el grupo para cumplir la FK.
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor()
        
        # Obtener ID profesor dueño del grupo
        cursor.execute("SELECT id_profesor FROM grupos WHERE id_grupo = %s", (id_grupo,))
        res_profe = cursor.fetchone()
        if not res_profe: return jsonify({"error": "Grupo sin profesor"}), 400
        id_profesor = res_profe[0]

        # INSERT / UPDATE Query usando tus campos
        sql = """
            INSERT INTO asistencias (asistencia, id_grupo, id_alumno, id_profesor, fecha_clase) 
            VALUES (%s, %s, %s, %s, %s) 
            ON DUPLICATE KEY UPDATE asistencia = %s
        """
        # Valores: (asistencia, grupo, alumno, profe, fecha) + (asistencia_update)
        cursor.execute(sql, (valor_asistencia, id_grupo, id_alumno, id_profesor, fecha_clase, valor_asistencia))
        conn.commit()
        
        return jsonify({"status": "success"})
        
    except Exception as e:
        print(f"Error SQL: {e}")
        return jsonify({"status": "error", "mensaje": str(e)}), 500
    finally:
        if conn: conn.close()

# --- API: OBTENER HISTORIAL (Adaptado a tu Schema) ---
@app.route("/api/obtener_asistencias", methods=["POST"])
def api_obtener_asistencias():
    conn = None
    try:
        data = request.get_json()
        fechas = data.get('fechas') # Lista de fechas ['2023-11-20', '2023-11-21']
        id_grupo = data.get('id_grupo') # Necesitamos filtrar por grupo también
        
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor(dictionary=True)
        
        # Crear placeholders para la lista de fechas
        format_strings = ','.join(['%s'] * len(fechas))
        
        query = f"""
            SELECT id_alumno, fecha_clase, asistencia 
            FROM asistencias 
            WHERE id_grupo = %s AND fecha_clase IN ({format_strings})
        """
        
        # Tupla de parámetros: (id_grupo, fecha1, fecha2, ...)
        params = [id_grupo] + fechas
        
        cursor.execute(query, params)
        resultados = cursor.fetchall()
        
        # Formatear fecha para JSON
        for row in resultados:
            row['fecha_clase'] = str(row['fecha_clase']) # Convertir date a string
            
        return jsonify(resultados)
        
    except Exception as e:
        print(e)
        return jsonify({"error": str(e)}), 500
    finally:
        if conn: conn.close()

@app.route("/api/obtener_comentarios/<int:id_alumno>", methods=["GET"])
def api_obtener_comentarios(id_alumno):
    conn = None
    try:
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor(dictionary=True)
        
        # Obtenemos id_comentario e id_profesor para validar permisos en el frontend
        cursor.execute("""
            SELECT c.id_comentario, c.descripcion, c.fecha_registro, c.id_profesor,
                   CONCAT(p.nombre, ' ', p.apellido_p) as profesor
            FROM comentarios c
            LEFT JOIN profesores p ON c.id_profesor = p.id_profesor
            WHERE c.id_alumno = %s
            ORDER BY c.fecha_registro DESC
        """, (id_alumno,))
        
        comentarios = cursor.fetchall()
        
        for c in comentarios:
            c['fecha'] = c['fecha_registro'].strftime("%d/%m/%Y %H:%M")
            
        return jsonify({'status': 'success', 'comentarios': comentarios})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500
    finally:
        if conn: conn.close()

# --- API: GUARDAR O EDITAR COMENTARIO ---
@app.route("/api/guardar_comentario", methods=["POST"])
def api_guardar_comentario():
    conn = None
    try:
        data = request.get_json()
        id_alumno = data.get('id_alumno')
        descripcion = data.get('descripcion')
        id_comentario = data.get('id_comentario') # Si viene, es edición
        
        # VALIDACIÓN DE SEGURIDAD: Usar siempre el ID de la sesión
        id_profesor_sesion = session.get('user_id')
        
        if not id_profesor_sesion:
            return jsonify({'status': 'error', 'message': 'No hay sesión activa'}), 401

        if not descripcion:
            return jsonify({'status': 'error', 'message': 'Comentario vacío'}), 400

        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor()
        
        if id_comentario:
            # --- EDICIÓN: Solo si el comentario pertenece al profesor logueado ---
            cursor.execute("""
                UPDATE comentarios SET descripcion = %s, fecha_registro = NOW()
                WHERE id_comentario = %s AND id_profesor = %s
            """, (descripcion, id_comentario, id_profesor_sesion))
            
            if cursor.rowcount == 0:
                return jsonify({'status': 'error', 'message': 'No tienes permiso para editar este comentario o no existe.'}), 403
        else:
            # --- INSERCIÓN NUEVA ---
            cursor.execute("""
                INSERT INTO comentarios (descripcion, id_alumno, id_profesor)
                VALUES (%s, %s, %s)
            """, (descripcion, id_alumno, id_profesor_sesion))
        
        conn.commit()
        return jsonify({'status': 'success'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500
    finally:
        if conn: conn.close()

# --- API: ELIMINAR COMENTARIO (NUEVA) ---
@app.route("/api/eliminar_comentario", methods=["POST"])
def api_eliminar_comentario():
    conn = None
    try:
        data = request.get_json()
        id_comentario = data.get('id_comentario')
        id_profesor_sesion = session.get('user_id') # Seguridad

        if not id_profesor_sesion: return jsonify({'status': 'error', 'message': 'Login requerido'}), 401

        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor()
        
        # Solo borra si coincide el ID del comentario Y el ID del profesor dueño
        cursor.execute("DELETE FROM comentarios WHERE id_comentario = %s AND id_profesor = %s", (id_comentario, id_profesor_sesion))
        
        if cursor.rowcount == 0:
             return jsonify({'status': 'error', 'message': 'No se pudo borrar (Permisos o no existe)'}), 403

        conn.commit()
        return jsonify({'status': 'success'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500
    finally:
        if conn: conn.close()

@app.route("/maestroinfo/<string:tipo>/<int:id>")
def maestroinfo(tipo, id):
    conn = None
    personal_data = None
    expediente_data = {}
    
    try:
        if tipo not in ['maestro', 'staff']: return "Error", 400
        table_name = "profesores" if tipo == 'maestro' else "staff"
        id_column = "id_profesor" if tipo == 'maestro' else "id_staff"
        
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor(dictionary=True)

        cursor.execute(f"SELECT * FROM {table_name} WHERE {id_column} = %s", (id,))
        personal_data = cursor.fetchone()

        if not personal_data: return "No encontrado", 404
        
        mongo_id = personal_data.get('id_expediente_mongo')
        if mongo_id:
            expediente_doc = expedientes_col.find_one({"_id": ObjectId(mongo_id)})
            if expediente_doc:
                for key, filepath in expediente_doc.get('documentos', {}).items():
                    # Aquí generamos la URL que redirige a la ruta /expediente/ver/...
                    # la cual finalmente redirige a Drive
                    if filepath:
                        expediente_data[key] = url_for(
                            'ver_documento_expediente', 
                            mongo_id=mongo_id, 
                            tipo_doc=key
                        )
                    else:
                        expediente_data[key] = None

        if personal_data.get("fecha_nacimiento"):
            personal_data["fecha_nacimiento"] = personal_data["fecha_nacimiento"].strftime("%d/%m/%Y")
            
        datos_fiscales = None
        if tipo == 'maestro':
            cursor.execute("SELECT * FROM profesores_datos_fiscales WHERE id_profesor = %s", (id,))
            datos_fiscales = cursor.fetchone()
            
    except Exception as e:
        return "Error interno", 500
    finally:
        if conn: conn.close()

    return render_template("maestroinfo.html", personal=personal_data, expediente=expediente_data, tipo=tipo, datos_fiscales=datos_fiscales)

@app.route("/nomina") #actualizar maestros
def nomina():
    return render_template("nomina.html")

@app.route("/perfil") #actualizar password
def perfil():
    return render_template("Perfil.html")

@app.route("/gestion_cursos")
def gestion_cursos():
    conn = None
    try:
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SHOW COLUMNS FROM cursos LIKE 'nivel'")
        niveles = parse_enum(cursor.fetchone())
        cursor.execute("SELECT id_idioma, nombre FROM idioma ORDER BY nombre")
        idiomas = cursor.fetchall()
        # Cursos (solo definición académica)
        cursor.execute("SELECT c.id_curso, i.nombre AS idioma_nombre, c.nivel, c.club FROM cursos c JOIN idioma i ON c.id_idioma = i.id_idioma ORDER BY i.nombre, c.nivel")
        cursos = cursor.fetchall()
        return render_template("cursos.html", niveles=niveles, idiomas=idiomas, cursos=cursos)
    except Exception as e: return f"Error: {e}", 500
    finally: 
        if conn: conn.close()

@app.route("/guardar_curso", methods=["POST"])
def guardar_curso():
    conn = None
    try:
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor()
        cursor.execute("INSERT INTO cursos (id_idioma, nivel, club) VALUES (%s, %s, %s)", (request.form.get('id_idioma'), request.form.get('nivel'), request.form.get('club')))
        conn.commit()
        return jsonify({'status': 'success', 'message': 'Curso registrado.'})
    except Exception as e: return jsonify({'status': 'error', 'message': str(e)}), 500
    finally: 
        if conn: conn.close()

@app.route("/eliminar_curso/<int:id_curso>", methods=["POST"])
def eliminar_curso(id_curso):
    conn = None
    try:
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM cursos WHERE id_curso = %s", (id_curso,))
        conn.commit()
        return jsonify({'status': 'success'})
    except Exception as e: return jsonify({'status': 'error', 'message': str(e)}), 500
    finally: 
        if conn: conn.close()

@app.route("/Horario")
def Horario():
    return redirect(url_for('gestion_horarios_base'))

def get_horarios_data():
    conn = None; data = []; sedes = set()
    try:
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM horario")
        for r in cursor.fetchall():
            sedes.add(r['sede'])
            try: s, e = r['hora'].split(' - ')
            except: s, e = "00:00", "00:00"
            day_map = {'Lun':1,'Mar':2,'Mié':3,'Jue':4,'Vie':5,'Sáb':6}
            for d in r['dias'].split(','):
                d_clean = d.strip()
                if d_clean in day_map:
                    data.append({'id':r['id_horario'], 'sede':r['sede'], 'dias_str':r['dias'], 'day':day_map[d_clean], 'time':s.strip(), 'end_time':e.strip()})
    except: pass
    finally: 
        if conn: conn.close()
    return sorted(list(sedes)), data

@app.route("/gestion_horarios_base")
def gestion_horarios_base():
    conn = None
    try:
        sedes, _ = get_horarios_data()
        
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor(dictionary=True)

        # 1. Catálogos para Crear Cursos
        cursor.execute("SELECT id_idioma, nombre FROM idioma ORDER BY nombre")
        idiomas = cursor.fetchall()

        cursor.execute("SHOW COLUMNS FROM cursos LIKE 'nivel'")
        niveles = parse_enum(cursor.fetchone())

        # 2. Profesores
        cursor.execute("SELECT id_profesor, CONCAT(nombre, ' ', apellido_p, ' ', apellido_m) AS nombre_completo FROM profesores")
        profesores = cursor.fetchall()

        # 3. Cursos Existentes
        cursor.execute("""
            SELECT c.id_curso, i.nombre AS idioma, c.nivel, c.club
            FROM cursos c 
            JOIN idioma i ON c.id_idioma = i.id_idioma 
            ORDER BY i.nombre, c.nivel
        """)
        cursos = cursor.fetchall()

        # 4. Horarios Disponibles
        cursor.execute("SELECT id_horario, CONCAT(dias, ' ', hora, ' (', sede, ')') as detalle FROM horario")
        horarios_select = cursor.fetchall()

        # ==========================================================
        # 5. GRUPOS EXISTENTES (CORREGIDO)
        # ==========================================================
        # El error estaba en el subquery COUNT(*). Ahora apunta a 'inscripciones_idioma'
        cursor.execute("""
            SELECT g.id_grupo, g.grupo AS nombre_grupo, g.numero_salon,
            CONCAT(p.nombre, ' ', p.apellido_p) AS profesor, 
            i.nombre AS idioma, c.nivel, c.club,
            h.dias, h.hora, h.sede,
            (SELECT COUNT(*) FROM inscripciones_idioma ii WHERE ii.id_grupo = g.id_grupo) AS cantidad_alumnos
            FROM grupos g
            LEFT JOIN profesores p ON g.id_profesor = p.id_profesor
            LEFT JOIN cursos c ON g.id_curso = c.id_curso
            LEFT JOIN idioma i ON c.id_idioma = i.id_idioma
            LEFT JOIN horario h ON g.id_horario = h.id_horario
            ORDER BY g.id_grupo DESC
        """)
        grupos = cursor.fetchall()

        return render_template("crearhorario.html", 
                               sedes=sedes, 
                               profesores=profesores, 
                               cursos=cursos, 
                               grupos=grupos, 
                               horarios=horarios_select,
                               idiomas=idiomas,
                               niveles=niveles)

    except Exception as e:
        return f"Error al cargar vista: {e}", 500
    finally:
        if conn: conn.close()

@app.route("/api/horarios_base", methods=["GET"])
def api_horarios_base():
    _, data = get_horarios_data()
    return jsonify(data)

@app.route("/guardar_horario_base", methods=["POST"])
def guardar_horario_base():
    conn = None
    try:
        sede = request.form.get('sede')
        days = request.form.getlist('dias[]')
        start, end = request.form.get('hora_inicio'), request.form.get('hora_fin')
        day_map = {'1': 'Lun', '2': 'Mar', '3': 'Mié', '4': 'Jue', '5': 'Vie', '6': 'Sáb'}
        dias_str = ', '.join([day_map[d] for d in days if d in day_map])
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor()
        cursor.execute("INSERT INTO horario (sede, dias, hora) VALUES (%s, %s, %s)", (sede, dias_str, f"{start} - {end}"))
        conn.commit()
        return jsonify({'status': 'success', 'message': 'Horario creado'}), 201
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500
    finally:
        if conn: conn.close()

@app.route("/editar_horario_base", methods=["POST"])
def editar_horario_base():
    conn = None
    try:
        data = request.get_json()
        dias_str = ', '.join(data.get('dias', []))
        hora_str = f"{data.get('hora_inicio')} - {data.get('hora_fin')}"
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor()
        cursor.execute("UPDATE horario SET sede=%s, dias=%s, hora=%s WHERE id_horario=%s", (data.get('sede'), dias_str, hora_str, data.get('id_horario')))
        conn.commit()
        return jsonify({'status': 'success'})
    except Exception as e: return jsonify({'status': 'error', 'message': str(e)}), 500
    finally: 
        if conn: conn.close()

@app.route("/eliminar_horario_base/<int:id_horario>", methods=["POST"])
def eliminar_horario_base(id_horario):
    conn = None
    try:
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM horario WHERE id_horario = %s", (id_horario,))
        conn.commit()
        return jsonify({'status': 'success'})

    except mysql.connector.Error as e:
        if e.errno == 1451:
            return jsonify({
                'status': 'error', 
                'message': 'No se puede eliminar: Hay alumnos inscritos o grupos asignados a este horario. Moverlos primero antes de borrar.'
            }), 400
        return jsonify({'status': 'error', 'message': f'Error de base de datos: {e}'}), 500

    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500
    finally: 
        if conn: conn.close()

@app.route("/api/horario_detail/<int:id_horario>", methods=["GET"])
def api_horario_detail(id_horario):
    conn = None
    try:
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM horario WHERE id_horario = %s", (id_horario,))
        row = cursor.fetchone()
        if not row: return jsonify({'status': 'error'}), 404
        s, e = row['hora'].split(' - ')
        return jsonify({'status': 'success', 'id_horario': row['id_horario'], 'sede': row['sede'], 'dias': row['dias'].split(', '), 'hora_inicio': s.strip(), 'hora_fin': e.strip()})
    finally: 
        if conn: conn.close()

@app.route("/editar_sede", methods=["POST"])
def editar_sede():
    conn = None
    try:
        data = request.get_json()
        old_name = data.get('old_name')
        new_name = data.get('new_name')
        
        if not old_name or not new_name:
            return jsonify({'status': 'error', 'message': 'Faltan datos.'}), 400
        
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor()
        
        # Actualiza el nombre de la sede en TODOS los horarios que la usen
        cursor.execute("UPDATE horario SET sede = %s WHERE sede = %s", (new_name, old_name))
        conn.commit()
        
        return jsonify({'status': 'success', 'message': 'Sede renombrada correctamente.'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500
    finally:
        if conn: conn.close()

@app.route("/eliminar_sede", methods=["POST"])
def eliminar_sede():
    conn = None
    try:
        data = request.get_json()
        sede_name = data.get('name')
        
        if not sede_name:
            return jsonify({'status': 'error', 'message': 'Falta el nombre de la sede.'}), 400
        
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor()
        
        # Intenta borrar todos los horarios de esa sede
        cursor.execute("DELETE FROM horario WHERE sede = %s", (sede_name,))
        
        if cursor.rowcount == 0:
             return jsonify({'status': 'error', 'message': 'No se encontraron horarios para esa sede o ya fue eliminada.'}), 404

        conn.commit()
        return jsonify({'status': 'success', 'message': f'Sede "{sede_name}" y sus horarios eliminados.'})
        
    except mysql.connector.Error as e:
        # Error 1451 ocurre si intentas borrar un horario que ya está asignado a un Grupo
        if e.errno == 1451: 
            return jsonify({'status': 'error', 'message': 'No se puede eliminar la sede: Hay Grupos activos asignados a estos horarios. Elimina los grupos primero.'}), 400
        return jsonify({'status': 'error', 'message': str(e)}), 500
    finally:
        if conn: conn.close()

@app.route("/grupos")
def grupos(): return redirect(url_for('gestion_horarios_base'))

@app.route("/guardar_grupo", methods=["POST"])
def guardar_grupo():
    conn = None
    try:
        f = request.form
        id_horario = f.get('id_horario') 

        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor()
        
        query = """
            INSERT INTO grupos (numero_salon, grupo, id_profesor, id_curso, id_horario) 
            VALUES (%s, %s, %s, %s, %s)
        """

        cursor.execute(query, (f['salon'], f['nombre_grupo'], f['id_profesor'], f['id_curso'], id_horario))
        
        conn.commit()
        
        logs_col.insert_one({
            "tipo_entidad": "grupo", 
            "accion": "creacion_grupo", 
            "detalle": f"Grupo {f['nombre_grupo']} creado con horario ID {id_horario}", 
            "fecha": datetime.utcnow()
        })
        
        return jsonify({'status': 'success', 'message': 'Grupo creado y horario asignado correctamente.'})
        
    except Exception as e: 
        return jsonify({'status': 'error', 'message': str(e)}), 500
    finally: 
        if conn: conn.close()

@app.route("/api/grupo_detail/<int:id_grupo>", methods=["GET"])
def api_grupo_detail(id_grupo):
    conn = None
    try:
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM grupos WHERE id_grupo = %s", (id_grupo,))
        grupo = cursor.fetchone()
        if grupo: return jsonify({'status': 'success', 'grupo': grupo})
        return jsonify({'status': 'error', 'message': 'Grupo no encontrado'}), 404
    except Exception as e: return jsonify({'status': 'error', 'message': str(e)}), 500
    finally: 
        if conn: conn.close()

@app.route("/editar_grupo", methods=["POST"])
def editar_grupo():
    conn = None
    try:
        f = request.form
        id_grupo = f.get('id_grupo')
        id_horario = f.get('id_horario') 

        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor()
        
        cursor.execute("""
            UPDATE grupos 
            SET numero_salon=%s, grupo=%s, id_profesor=%s, id_curso=%s, id_horario=%s
            WHERE id_grupo=%s
        """, (f['salon'], f['nombre_grupo'], f['id_profesor'], f['id_curso'], id_horario, id_grupo))
        
        conn.commit()
        return jsonify({'status': 'success', 'message': 'Grupo actualizado correctamente'})
    except Exception as e: 
        return jsonify({'status': 'error', 'message': str(e)}), 500
    finally: 
        if conn: conn.close()

@app.route("/eliminar_grupo/<int:id_grupo>", methods=["POST"])
def eliminar_grupo(id_grupo):
    conn = None
    try:
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM grupos WHERE id_grupo = %s", (id_grupo,))
        conn.commit()
        return jsonify({'status': 'success', 'message': 'Grupo eliminado'})
    except mysql.connector.Error as e:
        if e.errno == 1451: return jsonify({'status': 'error', 'message': 'Grupo con alumnos inscritos.'}), 400
        return jsonify({'status': 'error', 'message': str(e)}), 500
    finally: 
        if conn: conn.close()

@app.route("/api/curso_detail/<int:id_curso>", methods=["GET"])
def api_curso_detail(id_curso):
    """Obtiene los detalles de un curso o club para editarlo."""
    conn = None
    try:
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM cursos WHERE id_curso = %s", (id_curso,))
        curso = cursor.fetchone()
        if curso: 
            return jsonify({'status': 'success', 'curso': curso})
        return jsonify({'status': 'error', 'message': 'Curso no encontrado'}), 404
    except Exception as e: 
        return jsonify({'status': 'error', 'message': str(e)}), 500
    finally: 
        if conn: conn.close()

@app.route("/editar_curso", methods=["POST"])
def editar_curso():
    """Actualiza la información de un curso o club."""
    conn = None
    try:
        f = request.form
        id_curso = f.get('id_curso')
        id_idioma = f.get('id_idioma')
        nivel = f.get('nivel')
        club = f.get('club')
        
        # Si el usuario eligió "Curso Regular" en el frontend, 'club' vendrá vacío.
        # Lo convertimos a None para que se guarde como NULL en la base de datos.
        if not club or club.strip() == "":
            club = None

        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE cursos 
            SET id_idioma=%s, nivel=%s, club=%s 
            WHERE id_curso=%s
        """, (id_idioma, nivel, club, id_curso))
        
        conn.commit()
        return jsonify({'status': 'success', 'message': 'Definición académica actualizada.'})
    except Exception as e: 
        return jsonify({'status': 'error', 'message': str(e)}), 500
    finally: 
        if conn: conn.close()

# --- FIN RUTAS DE GESTIÓN DE CURSOS ---
@app.route("/reinscripciones") 
def reinscripciones():
    filtro = request.args.get("tipo", None) 
    inscripciones = [] 
    cursos = []
    grupos = []
    conteos = []
    stats_generales = {}

    conn = None
    cursor = None

    try:
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor(dictionary=True)

        # 1. ESTADÍSTICAS GENERALES
        cursor.execute("""
            SELECT COUNT(*) as total_general,
                COALESCE(SUM(CASE WHEN estado = 'Activo' THEN 1 ELSE 0 END), 0) as activos,
                COALESCE(SUM(CASE WHEN estado = 'Baja' THEN 1 ELSE 0 END), 0) as bajas,
                COALESCE(SUM(CASE WHEN estado = 'Baja temporal' THEN 1 ELSE 0 END), 0) as bajas_temporal
            FROM inscripciones_idioma
        """)
        stats_generales = cursor.fetchone()

        cursor.execute("""
            SELECT COUNT(*) as total_multi FROM (
                SELECT id_alumno FROM inscripciones_idioma GROUP BY id_alumno HAVING COUNT(DISTINCT id_idioma) > 1
            ) as subquery
        """)
        res_multi = cursor.fetchone()
        stats_generales['multi_idioma'] = res_multi['total_multi'] if res_multi else 0

        # 2. CONTEOS IDIOMA
        cursor.execute("""
            SELECT i.nombre, COUNT(ii.id_alumno) as total FROM idioma i
            LEFT JOIN inscripciones_idioma ii ON i.id_idioma = ii.id_idioma
            GROUP BY i.id_idioma, i.nombre ORDER BY total DESC
        """)
        conteos = cursor.fetchall()

        # 3. CATÁLOGOS
        cursor.execute("""
            SELECT c.id_curso, CONCAT(i.nombre, ' - Nivel ', c.nivel) AS nombre_completo, i.id_idioma 
            FROM cursos c JOIN idioma i ON c.id_idioma = i.id_idioma ORDER BY i.nombre, c.nivel
        """)
        cursos = cursor.fetchall()

        cursor.execute("""
            SELECT g.id_grupo, g.grupo, CONCAT(p.nombre, ' ', p.apellido_p) AS nombre_profesor, 
                   h.dias, h.hora, c.id_idioma, g.id_horario 
            FROM grupos g 
            LEFT JOIN profesores p ON g.id_profesor = p.id_profesor 
            LEFT JOIN horario h ON g.id_horario = h.id_horario 
            LEFT JOIN cursos c ON g.id_curso = c.id_curso
        """)
        grupos = cursor.fetchall()

        # 4. OBTENER INSCRIPCIONES (QUERY PRINCIPAL)
        # AGREGAMOS: ii.cobro_enviado
        query = """
             SELECT 
                ii.id_inscripcion, ii.estado, ii.id_grupo, ii.id_curso, 
                ii.id_horario AS id_horario_preferido, ii.cobro_enviado,
                a.id_alumno, a.matricula, a.nombre, a.apellido_p, a.apellido_m, a.correo_electronico, a.tipo_inscripcion, a.id_expediente_mongo,
                TIMESTAMPDIFF(YEAR, a.fecha_nacimiento, CURDATE()) AS edad,
                idi.nombre AS idioma_inscrito, idi.id_idioma,
                g.grupo AS nombre_grupo, CONCAT(p.nombre, ' ', p.apellido_p) AS maestro, c.nivel AS nivel_curso,
                (SELECT CONCAT(h.dias, ' | ', h.hora, ' (', h.sede, ')') FROM horario h WHERE h.id_horario = ii.id_horario) AS horario,
                (SELECT COUNT(*) FROM inscripciones_idioma WHERE id_alumno = a.id_alumno) as num_idiomas
             FROM inscripciones_idioma ii
             JOIN alumnos a ON ii.id_alumno = a.id_alumno
             JOIN idioma idi ON ii.id_idioma = idi.id_idioma
             LEFT JOIN grupos g ON ii.id_grupo = g.id_grupo
             LEFT JOIN profesores p ON g.id_profesor = p.id_profesor
             LEFT JOIN cursos c ON ii.id_curso = c.id_curso
        """
        
        if filtro: query += " WHERE a.tipo_inscripcion = %s "
        query += " ORDER BY a.apellido_p ASC, idi.nombre ASC"

        cursor.execute(query, (filtro,) if filtro else None)
        inscripciones = cursor.fetchall()

        # 5. PROCESAR DOCUMENTOS
        document_fields = ["acta_nacimiento", "identificacion", "formato_descuento", "documentos_comprobatorios", "comprobante_pago"]
        for ins in inscripciones:
            historial = obtener_historial_alumno(cursor, ins['id_alumno'])
            ins.update(historial)

            ins["documentos_urls"] = {}
            if ins.get("id_expediente_mongo"):
                try:
                    expediente = expedientes_col.find_one({"_id": ObjectId(ins["id_expediente_mongo"])})
                    docs = expediente.get("documentos", {}) if expediente else {}
                    for td in document_fields:
                        if docs.get(td):
                            ins["documentos_urls"][td] = url_for('ver_documento_expediente', mongo_id=ins["id_expediente_mongo"], tipo_doc=td)
                        else:
                            ins["documentos_urls"][td] = None
                except Exception: pass
            
            if ins.get("fecha_nacimiento"):
                ins["fecha_nacimiento"] = ins["fecha_nacimiento"].strftime("%d/%m/%Y")

    except Exception as e:
        print(f"Error en reinscripciones: {e}")
    finally:
        if cursor: cursor.close()
        if conn: conn.close()

    return render_template("reinscripciones.html", 
                           alumnos=inscripciones, 
                           filtro=filtro, 
                           cursos=cursos, 
                           grupos=grupos, 
                           conteos=conteos, 
                           stats=stats_generales)

def obtener_historial_alumno(cursor, id_alumno):
    """Busca la última calificación registrada para obtener datos anteriores."""
    tablas_calif = [
        ('calificaciones_adult', ['pronunciation', 'fluency', 'grammar_vocabulary', 'performance_skill', 'comprenhension', 'main_ideas', 'grammar_word_choice', 'punctuation_capitalization'], 5),
        ('calificaciones_ninos', ['pronunciacion', 'fluidez', 'gramatica_vocabulario', 'habilidades_pronunciacion', 'comprension', 'contenido', 'organizacion', 'lenguaje', 'gramatica', 'ortografia'], 3),
        ('calificaciones_lsm', ['expresiones_faciales', 'movimientos_corporales', 'movimiento_manos', 'identifica_ideograma', 'uos_mano_dominante', 'realiza_dactilogía', 'transmite_mensaje', 'detalles_coordinada', 'orden_secuencial', 'percibir_detalles', 'comprende_mensaje', 'recuerda_senas'], 3)
    ]
    
    mejor_registro = {'idioma_ant': '---', 'maestro_ant': '---', 'promedio_ant': '---'}
    mejor_fecha = None

    for tabla, campos, escala in tablas_calif:
        cols_sum = "+".join([f"CAST({c} AS DECIMAL(4,2))" for c in campos])
        query = f"""
            SELECT cal.fecha_registro, CONCAT(p.nombre, ' ', p.apellido_p) as profe, i.nombre as idioma, cur.nivel, ROUND(({cols_sum}) / {len(campos)}, 1) as promedio
            FROM {tabla} cal
            JOIN profesores p ON cal.id_profesor = p.id_profesor
            JOIN grupos g ON cal.id_grupo = g.id_grupo
            JOIN cursos cur ON g.id_curso = cur.id_curso
            JOIN idioma i ON cur.id_idioma = i.id_idioma
            WHERE cal.id_alumno = %s ORDER BY cal.fecha_registro DESC LIMIT 1
        """
        cursor.execute(query, (id_alumno,))
        res = cursor.fetchone()
        if res:
            if mejor_fecha is None or res['fecha_registro'] > mejor_fecha:
                mejor_fecha = res['fecha_registro']
                mejor_registro = {
                    'idioma_ant': f"{res['idioma']} {res['nivel']}",
                    'maestro_ant': res['profe'],
                    'promedio_ant': f"{res['promedio']}/{escala}"
                }
    return mejor_registro

@app.route("/api/alumnos_por_grupo/<int:id_grupo>", methods=["GET"])
def api_alumnos_por_grupo(id_grupo):
    """API Completa para vista detallada de grupo"""
    conn = None
    try:
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor(dictionary=True)
        
        cursor.execute("""
            SELECT g.grupo, g.numero_salon, CONCAT(p.nombre, ' ', p.apellido_p) AS profesor, i.nombre AS idioma, c.nivel
            FROM grupos g LEFT JOIN profesores p ON g.id_profesor = p.id_profesor LEFT JOIN cursos c ON g.id_curso = c.id_curso LEFT JOIN idioma i ON c.id_idioma = i.id_idioma
            WHERE g.id_grupo = %s
        """, (id_grupo,))
        info_grupo = cursor.fetchone()
        
        # AGREGAMOS: ii.cobro_enviado
        cursor.execute("""
            SELECT 
                ii.id_inscripcion, ii.estado, ii.id_grupo, ii.id_curso, 
                ii.id_horario AS id_horario_preferido, ii.cobro_enviado,
                a.id_alumno, a.matricula, a.nombre, a.apellido_p, a.correo_electronico, a.telefono, a.id_expediente_mongo, a.tipo_inscripcion,
                idi.nombre AS idioma_inscrito, idi.id_idioma,
                TIMESTAMPDIFF(YEAR, a.fecha_nacimiento, CURDATE()) AS edad,
                g.grupo AS nombre_grupo, CONCAT(p.nombre, ' ', p.apellido_p) AS maestro, c.nivel AS nivel_curso,
                (SELECT CONCAT(h.dias, ' | ', h.hora) FROM horario h WHERE h.id_horario = ii.id_horario) AS horario
            FROM inscripciones_idioma ii
            JOIN alumnos a ON ii.id_alumno = a.id_alumno
            JOIN idioma idi ON ii.id_idioma = idi.id_idioma
            LEFT JOIN grupos g ON ii.id_grupo = g.id_grupo
            LEFT JOIN profesores p ON g.id_profesor = p.id_profesor
            LEFT JOIN cursos c ON ii.id_curso = c.id_curso
            WHERE ii.id_grupo = %s 
            ORDER BY a.apellido_p ASC
        """, (id_grupo,))
        alumnos = cursor.fetchall()

        document_fields = ["acta_nacimiento", "identificacion", "formato_descuento", "documentos_comprobatorios", "comprobante_pago"]
        
        for ins in alumnos:
            historial = obtener_historial_alumno(cursor, ins['id_alumno'])
            ins.update(historial)
            
            ins["documentos_urls"] = {}
            if ins.get("id_expediente_mongo"):
                 try:
                    expediente = expedientes_col.find_one({"_id": ObjectId(ins["id_expediente_mongo"])})
                    docs = expediente.get("documentos", {}) if expediente else {}
                    for td in document_fields:
                        if docs.get(td): ins["documentos_urls"][td] = url_for('ver_documento_expediente', mongo_id=ins["id_expediente_mongo"], tipo_doc=td)
                        else: ins["documentos_urls"][td] = None
                 except: pass

        return jsonify({'status': 'success', 'grupo': info_grupo, 'alumnos': alumnos, 'total': len(alumnos)})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500
    finally:
        if conn: conn.close()

@app.route('/asignar_grupo_curso', methods=['POST'])
def asignar_grupo_curso():
    conn = None
    try:
        d = request.get_json()
        id_inscripcion = d.get('id_inscripcion')
        if not id_inscripcion: return jsonify({'status': 'error', 'message': 'Falta ID'}), 400

        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor()
        cursor.execute("UPDATE inscripciones_idioma SET id_grupo=%s, id_curso=%s WHERE id_inscripcion=%s", (d['id_grupo'], d['id_curso'], id_inscripcion))
        conn.commit()
        return jsonify({'status': 'success', 'message': 'Asignado correctamente'})
    except Exception as e: return jsonify({'status': 'error', 'message': str(e)}), 500
    finally: 
        if conn: conn.close()

@app.route('/desasignar_grupo_curso', methods=['POST'])
def desasignar_grupo_curso():
    conn = None
    try:
        id_inscripcion = request.get_json().get('id_inscripcion')
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor()
        cursor.execute("UPDATE inscripciones_idioma SET id_grupo = NULL, id_curso = NULL WHERE id_inscripcion = %s", (id_inscripcion,))
        conn.commit()
        return jsonify({'status': 'success'})
    except Exception as e: return jsonify({'status': 'error', 'message': str(e)}), 500
    finally: 
        if conn: conn.close()

@app.route("/actualizar_estado_alumno", methods=["POST"])
def actualizar_estado_alumno():
    conn = None
    try:
        data = request.get_json()
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor()
        cursor.execute("UPDATE inscripciones_idioma SET estado = %s WHERE id_inscripcion = %s", (data.get('nuevo_estado'), data.get('id_inscripcion')))
        conn.commit()
        return jsonify({'status': 'success'})
    except Exception as e: return jsonify({'status': 'error', 'message': str(e)}), 500
    finally: 
        if conn: conn.close()

@app.route("/enviar_cobro_factura", methods=["POST"])
def enviar_cobro_factura():
    conn = None
    temp_file_path = None
    try:
        data = request.get_json()
        id_alumno = data.get('id_alumno')
        id_inscripcion = data.get('id_inscripcion') # NECESARIO PARA MARCAR COMO PAGADO
        
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor(dictionary=True)
        
        # 1. Datos Alumno
        cursor.execute("SELECT nombre, apellido_p, apellido_m, correo_electronico, contraseña FROM alumnos WHERE id_alumno = %s", (id_alumno,))
        alumno = cursor.fetchone()
        
        if not alumno: return jsonify({'status': 'error', 'message': 'No encontrado'}), 404
        
        # 2. Credenciales si no tiene
        msg_extra = ""
        if not alumno.get('contraseña'):
            pwd = ''.join(secrets.choice(string.ascii_letters + string.digits) for i in range(10))
            h_pwd = generate_password_hash(pwd)
            cursor.execute("UPDATE alumnos SET contraseña=%s WHERE id_alumno=%s", (h_pwd, id_alumno))
            conn.commit()
            msg_extra = f"<p><b>Usuario:</b> {alumno['correo_electronico']}<br><b>Contraseña:</b> {pwd}</p>"

        # 3. Generar HTML Recibo
        contenido_recibo = f"""
        <html>
        <body style="font-family: sans-serif; padding: 40px;">
            <div style="border: 2px solid #566a93; padding: 20px; border-radius: 10px;">
                <h1 style="color: #566a93;">Aviso de Cobro - Centro de Idiomas UTR</h1>
                <hr>
                <p><strong>Alumno:</strong> {alumno['nombre']} {alumno['apellido_p']}</p>
                <p><strong>Fecha:</strong> {datetime.now().strftime('%d/%m/%Y')}</p>
                <h3>Detalle</h3>
                <p>Descuentos: {data.get('descuentos_aplicados')}</p>
                <h2 style="color: #27ae60;">Total a Pagar: {data.get('total_a_cobrar')}</h2>
                <hr>
                <p>Realizar pago en caja o transferencia.</p>
            </div>
        </body>
        </html>
        """
        filename = f"Cobro_{id_alumno}_{datetime.now().strftime('%Y%m%d%H%M')}.html"
        temp_file_path = os.path.join(app.root_path, filename)
        with open(temp_file_path, 'w', encoding='utf-8') as f: f.write(contenido_recibo)

        # 4. Enviar Correo
        if yag:
            yag.send(
                to=alumno['correo_electronico'], 
                subject="Aviso de Cobro - CI UTR", 
                contents=[f"Hola {alumno['nombre']}, adjunto tu aviso de cobro.", msg_extra], 
                attachments=temp_file_path
            )
            # 5. MARCAR COMO ENVIADO EN DB
            if id_inscripcion:
                cursor.execute("UPDATE inscripciones_idioma SET cobro_enviado = 1 WHERE id_inscripcion = %s", (id_inscripcion,))
                conn.commit()
            
            return jsonify({'status': 'success', 'message': 'Cobro enviado y registrado'})
        else:
            # Simulación Local (si no hay correo config)
            if id_inscripcion:
                cursor.execute("UPDATE inscripciones_idioma SET cobro_enviado = 1 WHERE id_inscripcion = %s", (id_inscripcion,))
                conn.commit()
            return jsonify({'status': 'success', 'message': 'Cobro registrado (Simulación Local)'})

    except Exception as e: return jsonify({'status': 'error', 'message': str(e)}), 500
    finally:
        if temp_file_path and os.path.exists(temp_file_path): os.remove(temp_file_path)
        if conn: conn.close()

@app.route("/Cerrar")
def cerrar():
    return redirect(url_for('inicio')) 

if __name__ == "__main__":
    app.run(debug=True)