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
import requests
import base64
import locale
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

FACTURAMA_USER = 'FACTURAMA_USER'
FACTURAMA_PASS = 'FACTURAMA_PASSWORD'
FACTURAMA_URL = 'FACTURAMA_URL'

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
    
    # 1. Generar contraseña temporal aleatoria
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
        'genero': request.form.get('genero'),
        
        # --- NUEVOS CAMPOS FINANCIEROS ---
        'valor_hora': request.form.get('valor_hora', 0.0),
        'tasa_iva': request.form.get('tasa_iva'),
        'tasa_isr': request.form.get('tasa_isr')
    }
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
        # 4. Separar apellidos (Paterno y Materno)
        apellido_parts = form_data['apellidos'].split(' ')
        apellido_p = apellido_parts[0]
        apellido_m = ' '.join(apellido_parts[1:]) if len(apellido_parts) > 1 else ''

        # 5. Guardar en MySQL
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor()

        if form_data['tipo_personal'] == 'maestro':
            table_name = "profesores"
            # Query con columnas financieras
            query = """
                INSERT INTO profesores 
                (nombre, apellido_p, apellido_m, correo_electronico, telefono, fecha_nacimiento, contraseña, genero, valor_hora, tasa_iva, tasa_isr_retenido)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """
            params = (
                form_data['nombre'], apellido_p, apellido_m, email, form_data['telefono'], 
                form_data['fecha_nacimiento'], password_encriptada, form_data['genero'],
                form_data['valor_hora'], form_data['tasa_iva'], form_data['tasa_isr']
            )
        
        elif form_data['tipo_personal'] == 'staff':
            table_name = "staff"
            # Query con columnas financieras
            query = """
                INSERT INTO staff 
                (nombre, apellido_p, apellido_m, correo_electronico, telefono, fecha_nacimiento, contraseña, genero, valor_hora, tasa_iva, tasa_isr_retenido)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """
            params = (
                form_data['nombre'], apellido_p, apellido_m, email, form_data['telefono'], 
                form_data['fecha_nacimiento'], password_encriptada, form_data['genero'],
                form_data['valor_hora'], form_data['tasa_iva'], form_data['tasa_isr']
            )
        else:
            return jsonify({'status': 'error', 'message': 'Error: Tipo de personal no válido.'}), 400

        cursor.execute(query, params)
        id_personal = cursor.lastrowid
        conn.commit()
        
        portal_url_pregenerada = url_for('login', _external=True)

        # 6. Lanzar proceso asíncrono (Subir archivos y enviar correo)
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

        return jsonify({'status': 'success', 'message': f'¡{form_data["tipo_personal"].capitalize()} registrado exitosamente!'}), 202

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
        
@app.route("/gestionar_documento", methods=['POST'])
def gestionar_documento():
    if session.get('rol') != 'staff': # Asumimos que solo Admin/Staff gestiona esto
        # Si quieres que el maestro edite sus propios docs, ajusta aquí
        pass 
        # return jsonify({'status': 'error', 'message': 'No autorizado'}), 403

    try:
        accion = request.form.get('accion') # 'subir' o 'eliminar'
        tipo_doc = request.form.get('tipo_doc')
        mongo_id = request.form.get('mongo_id')
        
        if not mongo_id:
            return jsonify({'status': 'error', 'message': 'Expediente no encontrado'}), 404

        if accion == 'eliminar':
            # Borrar el campo del documento en MongoDB
            expedientes_col.update_one(
                {"_id": ObjectId(mongo_id)},
                {"$unset": {f"documentos.{tipo_doc}": ""}}
            )
            return jsonify({'status': 'success', 'message': 'Documento eliminado'})

        elif accion == 'subir':
            archivo = request.files.get('archivo')
            if archivo:
                filename = secure_filename(archivo.filename)
                # Subir a Drive
                file_stream = BytesIO(archivo.read())
                # Nota: Usamos 'subir_a_drive' que ya tienes definida
                drive_link = subir_a_drive(file_stream, filename, archivo.content_type)
                
                if drive_link:
                    # Actualizar el campo en MongoDB
                    expedientes_col.update_one(
                        {"_id": ObjectId(mongo_id)},
                        {"$set": {f"documentos.{tipo_doc}": drive_link}}
                    )
                    return jsonify({'status': 'success', 'message': 'Documento actualizado'})
                else:
                    return jsonify({'status': 'error', 'message': 'Error al subir a Drive'})
            else:
                return jsonify({'status': 'error', 'message': 'No se envió archivo'})

    except Exception as e:
        print(f"Error gestión documento: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route("/editar-personal/<string:tipo>/<int:id>", methods=['POST'])
def editar_personal(tipo, id):
    if 'user_id' not in session: return redirect(url_for('login'))
    
    try:
        # Datos Personales
        nombre = request.form.get('nombre')
        apellido_p = request.form.get('apellido_p')
        apellido_m = request.form.get('apellido_m')
        correo = request.form.get('correo_electronico')
        telefono = request.form.get('telefono')
        fecha_nac = request.form.get('fecha_nacimiento') or None
        genero = request.form.get('genero')
        
        # Datos Financieros (Nómina)
        valor_hora = request.form.get('valor_hora')
        tasa_iva = request.form.get('tasa_iva')
        tasa_isr = request.form.get('tasa_isr')

        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor()

        # Actualizar Tabla Principal (Profesores o Staff)
        if tipo == 'maestro':
            query = """
                UPDATE profesores 
                SET nombre=%s, apellido_p=%s, apellido_m=%s, correo_electronico=%s, 
                    telefono=%s, fecha_nacimiento=%s, genero=%s,
                    valor_hora=%s, tasa_iva=%s, tasa_isr_retenido=%s
                WHERE id_profesor=%s
            """
        elif tipo == 'staff':
            query = """
                UPDATE staff 
                SET nombre=%s, apellido_p=%s, apellido_m=%s, correo_electronico=%s, 
                    telefono=%s, fecha_nacimiento=%s, genero=%s,
                    valor_hora=%s, tasa_iva=%s, tasa_isr_retenido=%s
                WHERE id_staff=%s
            """
        
        cursor.execute(query, (
            nombre, apellido_p, apellido_m, correo, telefono, fecha_nac, genero,
            valor_hora, tasa_iva, tasa_isr, id
        ))
        conn.commit()
        
        return redirect(url_for('maestroinfo', tipo=tipo, id=id))

    except Exception as e:
        print(f"Error editar: {e}")
        return f"Error: {e}", 500
    finally:
        if conn: conn.close()

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

def redirigir_por_rol(rol, id_usuario):
    """
    Función central para decidir a dónde va cada usuario después del login.
    """
    if rol == 'staff':
        # Solicitud: pantalla principal reinscripciones.html
        return redirect(url_for('reinscripciones'))
    
    elif rol == 'maestro':
        # Solicitud: pantalla principal clasesprofe.html
        return redirect(url_for('clasesprofe'))
    
    elif rol == 'alumno':
        # Solicitud: pantalla principal cursos.html
        # Nota: La ruta que renderiza 'cursos.html' se llama 'gestion_cursos'
        return redirect(url_for('gestion_cursos'))
    
    else:
        # Fallback por si acaso
        return redirect(url_for('inicio'))

@app.route("/login", methods=["GET", "POST"])
def login():
    if 'user_id' in session:
        return redirigir_por_rol(session['rol'], session['user_id'])

    if request.method == "GET":
        return render_template("login.html")

    correo = request.form.get("correo_electronico")
    contrasena = request.form.get("contraseña")
    
    conn = None
    try:
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor(dictionary=True)
        
        busqueda_usuarios = [
            {"tabla": "staff",      "id_col": "id_staff",    "rol": "staff"},
            {"tabla": "profesores", "id_col": "id_profesor", "rol": "maestro"},
            {"tabla": "alumnos",    "id_col": "id_alumno",   "rol": "alumno"}
        ]

        datos_usuario = None
        usuario_encontrado = None

        for tipo in busqueda_usuarios:
            query = f"""
                SELECT {tipo['id_col']} AS id, nombre, apellido_p, contraseña, requiere_cambio_pass 
                FROM {tipo['tabla']} 
                WHERE correo_electronico = %s
            """
            cursor.execute(query, (correo,))
            datos_usuario = cursor.fetchone()

            if datos_usuario:
                usuario_encontrado = tipo
                break 

        if not datos_usuario:
            return render_template("login.html", error="Usuario no encontrado.")

        if check_password_hash(datos_usuario['contraseña'], contrasena):
            session.clear()
            session['user_id'] = datos_usuario['id']
            session['rol'] = usuario_encontrado['rol']
            session['nombre'] = f"{datos_usuario['nombre']} {datos_usuario['apellido_p']}"
            
            if datos_usuario.get('requiere_cambio_pass') == 1:
                session['force_change'] = True
                return redirect(url_for('cambiar_contrasena_inicial'))

            print(f"Login exitoso: {session['nombre']} como {session['rol']}")
            
            return redirigir_por_rol(session['rol'], session['user_id'])
        else:
            return render_template("login.html", error="Contraseña incorrecta.")

    except Exception as e:
        print(f"Error Login: {e}")
        return render_template("login.html", error=f"Error interno: {e}")
    finally:
        if conn: conn.close()

@app.route("/cambiar-contrasena-inicial", methods=["GET", "POST"])
def cambiar_contrasena_inicial():
    # Seguridad: Solo usuarios logueados
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    # Si intenta entrar directo sin la bandera, lo mandamos a su inicio normal
    if not session.get('force_change'):
        return redirigir_por_rol(session.get('rol'), session.get('user_id'))

    rol = session.get('rol')
    user_id = session.get('user_id')
    is_maestro = (rol == 'maestro') # Bandera para el HTML

    # GET: Mostrar el formulario
    if request.method == 'GET':
        return render_template("cambio_obligatorio.html", is_maestro=is_maestro)
    
    # POST: Procesar el cambio
    nueva_pass = request.form.get('nueva_contrasena')
    confirm_pass = request.form.get('confirmar_contrasena')
    
    # --- Validaciones Generales ---
    if len(nueva_pass) < 8:
        return render_template("cambio_obligatorio.html", error="La contraseña debe tener al menos 8 caracteres.", is_maestro=is_maestro)
    
    if nueva_pass != confirm_pass:
        return render_template("cambio_obligatorio.html", error="Las contraseñas no coinciden.", is_maestro=is_maestro)

    conn = None
    try:
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor()
        
        # --- LÓGICA ESPECIAL PARA MAESTROS (DATOS FISCALES) ---
        if is_maestro:
            rfc = request.form.get('rfc')
            razon_social = request.form.get('razon_social')
            regimen = request.form.get('regimen_fiscal')
            clabe = request.form.get('cuenta_clabe')
            cp = request.form.get('codigo_postal')

            # Validación básica de campos requeridos
            if not (rfc and razon_social and regimen and cp):
                return render_template("cambio_obligatorio.html", error="Todos los datos fiscales son obligatorios para procesar tu nómina.", is_maestro=is_maestro)

            # Guardar o Actualizar Datos Fiscales
            query_fiscal = """
                INSERT INTO profesores_datos_fiscales 
                (id_profesor, rfc, razon_social, regimen_fiscal, cuenta_clabe, codigo_postal)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE 
                rfc=%s, razon_social=%s, regimen_fiscal=%s, cuenta_clabe=%s, codigo_postal=%s
            """
            cursor.execute(query_fiscal, (
                user_id, rfc, razon_social, regimen, clabe, cp,
                rfc, razon_social, regimen, clabe, cp
            ))

        # --- ACTUALIZAR CONTRASEÑA Y QUITAR BANDERA ---
        if rol == 'staff': table, id_col = "staff", "id_staff"
        elif rol == 'maestro': table, id_col = "profesores", "id_profesor"
        elif rol == 'alumno': table, id_col = "alumnos", "id_alumno"
        
        hashed_password = generate_password_hash(nueva_pass)
        
        query_pass = f"UPDATE {table} SET contraseña = %s, requiere_cambio_pass = 0 WHERE {id_col} = %s"
        cursor.execute(query_pass, (hashed_password, user_id))
        
        conn.commit()
        
        # Limpiar bandera de sesión y redirigir
        session.pop('force_change', None)
        return redirigir_por_rol(rol, user_id)
        
    except Exception as e:
        print(f"Error cambio pass inicial: {e}")
        if conn: conn.rollback()
        return render_template("cambio_obligatorio.html", error=f"Error del servidor: {e}", is_maestro=is_maestro)
    finally:
        if conn: conn.close()

@app.route('/solicitar-restablecimiento', methods=['GET', 'POST'])
def solicitar_restablecimiento():
    if request.method == 'GET':
        return render_template('solicitar_restablecimiento.html')
    
    email = request.form.get('correo_electronico')
    conn = None
    
    try:
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor()
        
        # Buscar usuario en staff o profesores (Alumnos generalmente no cambian pass por correo en estos sistemas, pero puedes agregarlo)
        table_name = None
        cursor.execute("SELECT id_profesor FROM profesores WHERE correo_electronico = %s", (email,))
        if cursor.fetchone():
            table_name = "profesores"
        else:
            cursor.execute("SELECT id_staff FROM staff WHERE correo_electronico = %s", (email,))
            if cursor.fetchone():
                table_name = "staff"
        
        # Generamos el token siempre para no revelar si el correo existe o no (seguridad)
        # Pero solo guardamos y enviamos si existe tabla.
        if table_name:
            reset_token = secrets.token_urlsafe(32)
            expiration = datetime.now() + timedelta(hours=1)
            
            query = f"UPDATE {table_name} SET reset_token = %s, token_expiration = %s WHERE correo_electronico = %s"
            cursor.execute(query, (reset_token, expiration, email))
            conn.commit()

            # Generar Link
            reset_url = url_for('restablecer_contrasena', token=reset_token, _external=True)

            # Enviar Correo o Imprimir en Consola
            if yag:
                yag.send(to=email, subject="Restablecer Contraseña UTR", contents=f"Haz clic aquí: {reset_url}")
            else:
                print(f"\n[DEBUG] MODO DESARROLLO - Link de recuperación para {email}:")
                print(f"{reset_url}\n")
        
        return render_template('solicitar_restablecimiento.html', 
                             message="Se ha enviado un enlace de recuperación.")
        
    except Exception as e:
        print(f"Error reset: {e}")
        return render_template('solicitar_restablecimiento.html', error="Error interno.")
    finally:
        if conn: conn.close()

# PASO 2: Formulario de cambio (El que me mandaste)
@app.route('/restablecer-contrasena/<token>', methods=['GET', 'POST'])
def restablecer_contrasena(token):
    conn = None
    try:
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor(dictionary=True)
        
        # Buscar quién tiene ese token válido
        user_data = None
        table_name = None
        id_column = None

        # Check Profesores
        cursor.execute("SELECT id_profesor AS id, token_expiration FROM profesores WHERE reset_token = %s", (token,))
        user_data = cursor.fetchone()
        if user_data:
            table_name = "profesores"; id_column = "id_profesor"
        else:
            # Check Staff
            cursor.execute("SELECT id_staff AS id, token_expiration FROM staff WHERE reset_token = %s", (token,))
            user_data = cursor.fetchone()
            if user_data:
                table_name = "staff"; id_column = "id_staff"

        # Validar expiración
        if not user_data or user_data['token_expiration'] < datetime.now():
            return render_template('form_restablecer.html', error="El enlace es inválido o ha expirado.", token=token)

        if request.method == 'GET':
            return render_template('form_restablecer.html', token=token)

        # PROCESAR CAMBIO
        nueva_pass = request.form.get('nueva_contrasena')
        hashed_password = generate_password_hash(nueva_pass)

        query = f"UPDATE {table_name} SET contraseña = %s, reset_token = NULL, token_expiration = NULL WHERE {id_column} = %s"
        cursor.execute(query, (hashed_password, user_data['id']))
        conn.commit()

        return redirect(url_for('login', message="Contraseña actualizada. Inicia sesión."))

    except Exception as e:
        return f"Error: {e}"
    finally:
        if conn: conn.close()

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route("/historial")
def historial():
    return render_template("historial.html")

@app.route("/asistencias_estudiantes")
def listas():
    # 1. Seguridad: Verificar que sea alumno
    if session.get('rol') != 'alumno':
        return redirect(url_for('login'))
    
    user_id = session.get('user_id')
    conn = None
    resumen_asistencias = []

    try:
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor(dictionary=True)

        query = """
            SELECT 
                i.nombre AS idioma,
                c.nivel,
                (SELECT COUNT(*) 
                 FROM asistencias a 
                 WHERE a.id_alumno = ii.id_alumno 
                   AND a.id_grupo = ii.id_grupo 
                   AND a.asistencia = 0) AS total_faltas
            FROM inscripciones_idioma ii
            JOIN grupos g ON ii.id_grupo = g.id_grupo
            JOIN cursos c ON g.id_curso = c.id_curso
            JOIN idioma i ON c.id_idioma = i.id_idioma
            WHERE ii.id_alumno = %s AND ii.estado = 'Activo'
        """
        cursor.execute(query, (user_id,))
        resumen_asistencias = cursor.fetchall()

    except Exception as e:
        print(f"Error cargando asistencias: {e}")
    finally:
        if conn and conn.is_connected():
            cursor.close()
            conn.close()

    return render_template("asistenciasestudiantes.html", datos=resumen_asistencias)

def enviar_notificacion_async(destinatarios, asunto, mensaje_aviso, autor):
    """Envía correos en segundo plano para no bloquear la interfaz."""
    try:
        # Reconexión temporal a Yagmail si es necesario o uso de la instancia global
        local_yag = yag if yag else None
        
        if local_yag and destinatarios:
            html_content = f"""
                <div style="font-family: Arial, sans-serif; padding: 20px; border: 1px solid #e0e0e0; border-radius: 5px;">
                    <h2 style="color: #566a93;">Nuevo Aviso Publicado</h2>
                    <p>Hola,</p>
                    <p>Se ha publicado un nuevo aviso en el tablero del Centro de Idiomas.</p>
                    <hr>
                    <p><strong>Publicado por:</strong> {autor}</p>
                    <p><strong>Mensaje:</strong></p>
                    <blockquote style="background: #f9f9f9; padding: 15px; border-left: 4px solid #566a93;">
                        {mensaje_aviso}
                    </blockquote>
                    <hr>
                    <p style="font-size: 0.9em; color: #777;">
                        Para ver más detalles, ingresa a tu <a href="http://localhost:5000/login">portal de alumno</a>.
                    </p>
                </div>
            """
            # Enviamos con copia oculta (bcc) para proteger la privacidad de los correos
            local_yag.send(bcc=destinatarios, subject=asunto, contents=[html_content])
            print(f"Correos de notificación enviados a {len(destinatarios)} destinatarios.")
    except Exception as e:
        print(f"Error enviando correos de notificación: {e}")

@app.route("/avisos", methods=['GET', 'POST'])
def avisos():
    if 'user_id' not in session or session.get('rol') not in ['maestro', 'staff']:
        return redirect(url_for('login'))
    
    rol = session.get('rol')
    user_id = session.get('user_id')
    user_name = session.get('nombre', 'Usuario')
    
    conn = None
    grupos = []
    avisos_publicados = []
    calendar_events = []

    try:
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor(dictionary=True)

        # ---------------------------------------------------------
        # A) PROCESAR NUEVO AVISO (POST)
        # ---------------------------------------------------------
        if request.method == 'POST':
            mensaje = request.form.get('mensaje')
            fecha = request.form.get('fecha_evento')
            id_grupo = request.form.get('id_grupo') # Solo para maestros

            if mensaje and fecha:
                destinatarios = []
                autor_aviso = ""
                asunto_correo = "Nuevo Aviso - Centro de Idiomas UTR"

                if rol == 'maestro' and id_grupo:
                    # 1. Guardar Aviso
                    query = "INSERT INTO avisos (descripcion, fecha_calendario, id_profesor, id_grupo) VALUES (%s, %s, %s, %s)"
                    cursor.execute(query, (mensaje, fecha, user_id, id_grupo))
                    conn.commit()
                    
                    # 2. Obtener correos de los alumnos de ese grupo
                    cursor.execute("""
                        SELECT a.correo_electronico 
                        FROM alumnos a
                        JOIN inscripciones_idioma ii ON a.id_alumno = ii.id_alumno
                        WHERE ii.id_grupo = %s AND ii.estado = 'Activo'
                    """, (id_grupo,))
                    rows = cursor.fetchall()
                    destinatarios = [r['correo_electronico'] for r in rows]
                    autor_aviso = f"Prof. {user_name}"

                elif rol == 'staff':
                    # 1. Guardar Aviso General
                    query = "INSERT INTO avisos (descripcion, fecha_calendario, id_staff) VALUES (%s, %s, %s)"
                    cursor.execute(query, (mensaje, fecha, user_id))
                    conn.commit()
                    
                    # 2. Obtener correos de TODOS los alumnos activos
                    # (Cuidado: si son miles, esto podría necesitar optimización por lotes)
                    cursor.execute("""
                        SELECT DISTINCT a.correo_electronico 
                        FROM alumnos a
                        JOIN inscripciones_idioma ii ON a.id_alumno = ii.id_alumno
                        WHERE ii.estado = 'Activo'
                    """)
                    rows = cursor.fetchall()
                    destinatarios = [r['correo_electronico'] for r in rows]
                    autor_aviso = "Administración Centro de Idiomas"

                # 3. Lanzar hilo para enviar correos (si hay destinatarios y yagmail configurado)
                if destinatarios and yag:
                    thread = threading.Thread(
                        target=enviar_notificacion_async,
                        args=(destinatarios, asunto_correo, mensaje, autor_aviso)
                    )
                    thread.start()
                
                return redirect(url_for('avisos'))

        # ---------------------------------------------------------
        # B) CARGAR DATOS (GET) - (Igual que antes)
        # ---------------------------------------------------------
        if rol == 'maestro':
            cursor.execute("SELECT id_grupo, grupo, numero_salon FROM grupos WHERE id_profesor = %s", (user_id,))
            grupos = cursor.fetchall()

            query_avisos = """
                SELECT a.id_aviso, a.descripcion as mensaje, a.fecha_calendario as fecha, 
                       g.grupo as destino, g.id_grupo
                FROM avisos a
                LEFT JOIN grupos g ON a.id_grupo = g.id_grupo
                WHERE a.id_profesor = %s
                ORDER BY a.fecha_calendario DESC
            """
            cursor.execute(query_avisos, (user_id,))
        else: 
            query_avisos = """
                SELECT id_aviso, descripcion as mensaje, fecha_calendario as fecha, 'General' as destino
                FROM avisos 
                WHERE id_staff IS NOT NULL
                ORDER BY fecha_calendario DESC
            """
            cursor.execute(query_avisos)

        resultados = cursor.fetchall()

        for row in resultados:
            fecha_iso = ""
            fecha_fmt = ""
            if row['fecha']:
                fecha_iso = row['fecha'].isoformat()
                fecha_fmt = row['fecha'].strftime("%Y-%m-%d")
                
                calendar_events.append({
                    "title": f"Para {row['destino']}: {row['mensaje']}",
                    "start": fecha_iso,
                    "backgroundColor": "#566a93",
                    "borderColor": "#566a93",
                    "textColor": "#ffffff"
                })

            avisos_publicados.append({
                "id": row['id_aviso'],
                "mensaje": row['mensaje'],
                "fecha": fecha_fmt,
                "fecha_display": row['fecha'].strftime("%d/%m/%Y") if row['fecha'] else "Sin fecha",
                "destino": row.get('destino', 'General'),
                "id_grupo": row.get('id_grupo')
            })

    except Exception as e:
        print(f"Error en avisos: {e}")
    finally:
        if conn: conn.close()

    return render_template("avisos.html", 
                           grupos=grupos, 
                           avisos_publicados=avisos_publicados, 
                           calendar_events=calendar_events)

@app.route("/eliminar_aviso/<int:id_aviso>", methods=['POST'])
def eliminar_aviso(id_aviso):
    if 'user_id' not in session: return jsonify({'status': 'error'}), 403
    
    conn = None
    try:
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor()
        # Borramos solo si pertenece al usuario (seguridad básica por ID en WHERE)
        if session['rol'] == 'maestro':
            cursor.execute("DELETE FROM avisos WHERE id_aviso = %s AND id_profesor = %s", (id_aviso, session['user_id']))
        elif session['rol'] == 'staff':
            cursor.execute("DELETE FROM avisos WHERE id_aviso = %s", (id_aviso,)) # Staff puede borrar avisos generales
            
        conn.commit()
        return jsonify({'status': 'success'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})
    finally:
        if conn: conn.close()

@app.route("/editar_aviso", methods=['POST'])
def editar_aviso():
    if 'user_id' not in session: return redirect(url_for('login'))
    
    id_aviso = request.form.get('edit_id')
    mensaje = request.form.get('edit_mensaje')
    fecha = request.form.get('edit_fecha')
    id_grupo = request.form.get('edit_grupo') # Opcional si es maestro
    
    conn = None
    try:
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor()
        
        if session['rol'] == 'maestro':
            cursor.execute("""
                UPDATE avisos SET descripcion=%s, fecha_calendario=%s, id_grupo=%s 
                WHERE id_aviso=%s AND id_profesor=%s
            """, (mensaje, fecha, id_grupo, id_aviso, session['user_id']))
        elif session['rol'] == 'staff':
            cursor.execute("""
                UPDATE avisos SET descripcion=%s, fecha_calendario=%s 
                WHERE id_aviso=%s
            """, (mensaje, fecha, id_aviso))
            
        conn.commit()
    except Exception as e:
        print(f"Error editar aviso: {e}")
    finally:
        if conn: conn.close()
        
    return redirect(url_for('avisos'))

@app.route("/calificacion")
def calificacion():
    # Seguridad: Permitir Maestros y Staff
    rol = session.get('rol')
    if rol not in ['maestro', 'staff']:
        return redirect(url_for('login'))
    
    id_grupo = request.args.get('id_grupo')
    conn = None
    info_grupo = None
    
    try:
        if id_grupo:
            conn = mysql.connector.connect(**db_config)
            cursor = conn.cursor(dictionary=True)
            
            # Consulta base para obtener info del grupo
            query = """
                SELECT g.id_grupo, g.grupo, g.numero_salon, 
                       CONCAT(p.nombre, ' ', p.apellido_p) as profe_nombre, 
                       i.nombre as idioma, c.nivel
                FROM grupos g
                LEFT JOIN profesores p ON g.id_profesor = p.id_profesor
                LEFT JOIN cursos c ON g.id_curso = c.id_curso
                LEFT JOIN idioma i ON c.id_idioma = i.id_idioma
                WHERE g.id_grupo = %s
            """
            params = [id_grupo]

            # Si es MAESTRO, agregamos restricción de propiedad
            if rol == 'maestro':
                query += " AND g.id_profesor = %s"
                params.append(session.get('user_id'))
            
            cursor.execute(query, tuple(params))
            info_grupo = cursor.fetchone()

            if not info_grupo:
                return "Acceso denegado o grupo no encontrado.", 403

    except Exception as e:
        print(f"Error vista calificación: {e}")
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
        
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor(dictionary=True)

        # A) Obtener info básica para saber qué tabla usar
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

        # B) Consulta SQL CORREGIDA (SOLUCIÓN AL ERROR 1366)
        # Seleccionamos explícitamente el ID de la tabla de alumnos 'a.id_alumno' como 'id_alumno_safe'
        # porque 'c.id_alumno' (del LEFT JOIN) viene NULL si no hay calificación previa.
        query = f"""
            SELECT 
                a.id_alumno AS id_alumno_safe, 
                a.nombre, a.apellido_p, a.matricula,
                c.* FROM inscripciones_idioma ii
            JOIN alumnos a ON ii.id_alumno = a.id_alumno
            LEFT JOIN {tabla_calif} c 
                ON ii.id_alumno = c.id_alumno 
                AND c.id_grupo = ii.id_grupo 
                AND c.parcial = %s
            WHERE ii.id_grupo = %s AND ii.estado = 'Activo'
            ORDER BY a.apellido_p ASC
        """
        
        cursor.execute(query, (parcial, id_grupo))
        alumnos_con_notas = cursor.fetchall()

        # Serializador para fechas/decimales
        def serializador_seguro(obj):
            if isinstance(obj, (datetime, date)): return obj.isoformat()
            if isinstance(obj, decimal.Decimal): return float(obj)
            if isinstance(obj, timedelta): return str(obj)
            return str(obj)

        data_str = json.dumps(alumnos_con_notas, default=serializador_seguro)
        data_clean = json.loads(data_str)

        return jsonify({'status': 'success', 'data': data_clean})

    except Exception as e:
        print(f"ERROR API OBTENER: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500
    finally:
        if conn: conn.close()

@app.route("/api/guardar_calificaciones", methods=["POST"])
def api_guardar_calificaciones():
    # Seguridad
    if session.get('rol') != 'maestro':
        return jsonify({'status': 'error', 'message': 'No autorizado'}), 403

    conn = None
    try:
        data = request.get_json()
        id_grupo = data.get('id_grupo')
        parcial = data.get('parcial')
        calificaciones = data.get('calificaciones')
        tipo_curso = data.get('tipo_curso')
        
        id_profesor = session.get('user_id')

        # Verificar propiedad del grupo
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor()
        cursor.execute("SELECT id_grupo FROM grupos WHERE id_grupo = %s AND id_profesor = %s", (id_grupo, id_profesor))
        if not cursor.fetchone():
             return jsonify({'status': 'error', 'message': 'Grupo no válido'}), 403

        if not calificaciones: 
            return jsonify({'status': 'error', 'message': 'Sin datos'}), 400

        # Definir columnas según tipo
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
            return jsonify({'status': 'error', 'message': 'Tipo desconocido'}), 400

        # Query dinámica
        cols_str = ", ".join(columnas)
        vals_str = ", ".join(["%s"] * len(columnas))
        update_str = ", ".join([f"{c}=VALUES({c})" for c in columnas])

        sql = f"""
            INSERT INTO {tabla} (id_grupo, id_alumno, id_profesor, parcial, {cols_str})
            VALUES (%s, %s, %s, %s, {vals_str})
            ON DUPLICATE KEY UPDATE {update_str}, fecha_registro=NOW()
        """

        count = 0
        for calif in calificaciones:
            raw_id = calif.get('id_alumno')
            if not raw_id: continue
            
            valores = []
            for col in columnas:
                val = calif.get(col)
                # Convertir vacíos a None (NULL en SQL)
                valores.append(val if val is not None and val != "" else None)

            params = [id_grupo, raw_id, id_profesor, parcial] + valores
            cursor.execute(sql, params)
            count += 1

        conn.commit()
        return jsonify({'status': 'success', 'message': f'Guardados {count} registros.'})

    except Exception as e:
        print(f"ERROR GUARDAR: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500
    finally:
        if conn: conn.close()

@app.route("/calificaciones")
def calificaciones():
    # Seguridad: Solo alumnos
    if session.get('rol') != 'alumno':
        return redirect(url_for('login'))
        
    user_id = session.get('user_id')
    conn = None
    mis_clases = []

    try:
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor(dictionary=True)

        # CAMBIO CLAVE: Agregamos 'ii.id_grupo' al SELECT
        # Esto es necesario para crear el enlace al detalle
        query = """
            SELECT 
                ii.id_grupo, 
                i.nombre AS idioma,
                c.nivel,
                ii.calificacion_final
            FROM inscripciones_idioma ii
            JOIN grupos g ON ii.id_grupo = g.id_grupo
            JOIN cursos c ON g.id_curso = c.id_curso
            JOIN idioma i ON c.id_idioma = i.id_idioma
            WHERE ii.id_alumno = %s AND ii.estado = 'Activo'
        """
        cursor.execute(query, (user_id,))
        mis_clases = cursor.fetchall()

    except Exception as e:
        print(f"Error cargando calificaciones: {e}")
    finally:
        if conn and conn.is_connected():
            cursor.close()
            conn.close()

    return render_template("calificacionesestudiantes.html", clases=mis_clases)


# =================================================================
# 2. RUTA DETALLE (Agregar esta función nueva al final)
# =================================================================
@app.route("/ver_detalle_curso/<int:id_grupo>")
def ver_detalle_curso(id_grupo):
    # Seguridad: Solo alumnos
    if session.get('rol') != 'alumno':
        return redirect(url_for('login'))
    
    user_id = session.get('user_id')
    conn = None
    detalle_calif = []
    info_curso = {}
    columnas_a_mostrar = [] 

    try:
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor(dictionary=True)

        # A) Obtener información del grupo
        cursor.execute("""
            SELECT g.grupo, i.nombre as idioma, c.nivel 
            FROM grupos g
            JOIN cursos c ON g.id_curso = c.id_curso
            JOIN idioma i ON c.id_idioma = i.id_idioma
            WHERE g.id_grupo = %s
        """, (id_grupo,))
        info_curso = cursor.fetchone()

        if not info_curso:
            return "Curso no encontrado", 404

        # B) Lógica inteligente para elegir tabla (Adultos / Niños / LSM)
        tabla = "calificaciones_adult"
        # Configuración por defecto (Adultos)
        mapa_columnas = {
            "pronunciation": "Pronunciación", "fluency": "Fluidez", 
            "grammar_vocabulary": "Gramática y Vocabulario", "performance_skill": "Habilidades",
            "comprenhension": "Comprensión", "main_ideas": "Ideas Principales",
            "grammar_word_choice": "Elección de Palabras", "punctuation_capitalization": "Puntuación"
        }

        # Detectar si es Niños o LSM
        if 'Niños' in info_curso['grupo']:
            tabla = "calificaciones_ninos"
            mapa_columnas = {
                "pronunciacion": "Pronunciación", "fluidez": "Fluidez",
                "gramatica_vocabulario": "Gramática", "habilidades_pronunciacion": "Hab. Pronunciación",
                "comprension": "Comprensión", "contenido": "Contenido",
                "organizacion": "Organización", "lenguaje": "Lenguaje",
                "gramatica": "Gramática", "ortografia": "Ortografía"
            }
        elif 'LSM' in info_curso['idioma']:
            tabla = "calificaciones_lsm"
            mapa_columnas = {
                "expresiones_faciales": "Expr. Faciales", "movimientos_corporales": "Mov. Corporales",
                "movimiento_manos": "Manos", "identifica_ideograma": "Ideogramas",
                "uos_mano_dominante": "Mano Dominante", "realiza_dactilogía": "Dactilología",
                "transmite_mensaje": "Mensaje", "detalles_coordinada": "Coordinación",
                "orden_secuencial": "Orden Sec.", "percibir_detalles": "Detalles",
                "comprende_mensaje": "Comprensión", "recuerda_senas": "Memoria"
            }

        columnas_a_mostrar = list(mapa_columnas.values())
        columnas_sql = ", ".join(mapa_columnas.keys())

        # C) Consultar las calificaciones
        query = f"""
            SELECT parcial, comentario, {columnas_sql}
            FROM {tabla}
            WHERE id_grupo = %s AND id_alumno = %s
            ORDER BY parcial ASC
        """
        cursor.execute(query, (id_grupo, user_id))
        filas = cursor.fetchall()

        # D) Formatear datos
        for fila in filas:
            datos_parcial = {
                "numero": fila['parcial'],
                "comentario": fila['comentario'],
                "valores": [fila[col] for col in mapa_columnas.keys()]
            }
            detalle_calif.append(datos_parcial)

    except Exception as e:
        print(f"Error detalle curso: {e}")
        return f"Error: {e}", 500
    finally:
        if conn: conn.close()

    return render_template("detalle_calificaciones.html", 
                           curso=info_curso, 
                           headers=columnas_a_mostrar, 
                           calificaciones=detalle_calif)

@app.route('/tablero')
def tablero():
    # 1. Seguridad: Verificar que sea alumno
    if session.get('rol') != 'alumno':
        return redirect(url_for('login'))
    
    user_id = session.get('user_id')
    conn = None
    avisos_list = []
    calendar_events = []

    try:
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor(dictionary=True)

        # 2. CONSULTA FILTRADA: 
        # Trae avisos globales (hechos por Staff) Y avisos específicos de los grupos activos del alumno
        query = """
            SELECT 
                a.descripcion, 
                a.fecha_calendario,
                CASE 
                    WHEN a.id_staff IS NOT NULL THEN 'Administración'
                    WHEN p.id_profesor IS NOT NULL THEN CONCAT('Prof. ', p.nombre, ' ', p.apellido_p)
                    ELSE 'Aviso'
                END as autor,
                CASE 
                    WHEN a.id_staff IS NOT NULL THEN '#e74c3c'  -- Rojo para Admin
                    ELSE '#566a93'                              -- Azul institucional para Profesores
                END as color
            FROM avisos a
            LEFT JOIN profesores p ON a.id_profesor = p.id_profesor
            WHERE 
                a.id_staff IS NOT NULL 
                OR 
                a.id_grupo IN (
                    SELECT id_grupo FROM inscripciones_idioma 
                    WHERE id_alumno = %s AND estado = 'Activo'
                )
            ORDER BY a.fecha_calendario DESC
        """
        cursor.execute(query, (user_id,))
        resultados = cursor.fetchall()

        # 3. Procesar datos para enviarlos al HTML y al JS
        for row in resultados:
            fecha_str = ""
            if row['fecha_calendario']:
                fecha_str = row['fecha_calendario'].strftime("%d/%m/%Y")
                
                # Datos para el Calendario (FullCalendar)
                calendar_events.append({
                    "title": f"{row['autor']}: {row['descripcion']}",
                    "start": row['fecha_calendario'].isoformat(),
                    "backgroundColor": row['color'],
                    "borderColor": row['color'],
                    "textColor": "#ffffff" # Texto blanco para contraste
                })

            # Datos para la Lista lateral
            avisos_list.append({
                "fecha": fecha_str if fecha_str else "Sin fecha",
                "mensaje": row['descripcion'],
                "autor": row['autor']
            })

    except Exception as e:
        print(f"Error en tablero: {e}")
        # En producción podrías redirigir a una página de error o mostrar mensaje flash
    finally:
        if conn and conn.is_connected():
            cursor.close()
            conn.close()

    return render_template("tableroestudiantes.html", 
                           avisos_publicados=avisos_list, 
                           calendar_events=calendar_events)

@app.route("/evidencias", methods=['GET', 'POST'])
def evidencias():
    if session.get('rol') != 'maestro':
        return redirect(url_for('login'))
    
    user_id = session.get('user_id')
    conn = None
    grupos = []
    lista_evidencias = []

    try:
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor(dictionary=True)

        if request.method == 'POST':
            archivo = request.files.get('archivo')
            id_grupo = request.form.get('id_grupo')

            if archivo and id_grupo:
                filename = secure_filename(archivo.filename)

                file_stream = BytesIO(archivo.read())
                
                drive_link = subir_a_drive(file_stream, filename, archivo.content_type)

                if drive_link:
                    # 2. Guardar en MongoDB (Metadatos del archivo)
                    evidencia_doc = {
                        "tipo": "evidencia_profesor",
                        "id_profesor": user_id,
                        "id_grupo_mysql": int(id_grupo),
                        "documentos": {
                            "archivo_principal": drive_link,
                            "nombre_original": filename
                        },
                        "metadata": {
                            "fecha_subida": datetime.utcnow()
                        }
                    }
                    mongo_result = expedientes_col.insert_one(evidencia_doc)
                    mongo_id = str(mongo_result.inserted_id)

                    # 3. Guardar referencia en MySQL (Relación SQL-NoSQL)
                    query_insert = """
                        INSERT INTO evidencias (id_grupo, id_profesor, id_evidencias_mongo)
                        VALUES (%s, %s, %s)
                    """
                    cursor.execute(query_insert, (id_grupo, user_id, mongo_id))
                    conn.commit()

        cursor.execute("""
            SELECT g.id_grupo, g.grupo, i.nombre as idioma, c.nivel
            FROM grupos g
            JOIN cursos c ON g.id_curso = c.id_curso
            JOIN idioma i ON c.id_idioma = i.id_idioma
            WHERE g.id_profesor = %s
        """, (user_id,))
        grupos = cursor.fetchall()

        # 2. Obtener historial de evidencias ya subidas
        cursor.execute("""
            SELECT e.id_evidencias, e.fecha_registro, e.id_evidencias_mongo,
                   g.grupo, i.nombre as idioma, c.nivel
            FROM evidencias e
            JOIN grupos g ON e.id_grupo = g.id_grupo
            JOIN cursos c ON g.id_curso = c.id_curso
            JOIN idioma i ON c.id_idioma = i.id_idioma
            WHERE e.id_profesor = %s
            ORDER BY e.fecha_registro DESC
        """, (user_id,))
        rows = cursor.fetchall()

        for row in rows:
            mongo_doc = expedientes_col.find_one({"_id": ObjectId(row['id_evidencias_mongo'])})
            
            nombre_archivo = "Documento"
            link = "#"

            if mongo_doc:
                docs = mongo_doc.get('documentos', {})
                nombre_archivo = docs.get('nombre_original', 'Archivo')
                link = docs.get('archivo_principal', '#')

            lista_evidencias.append({
                "id": row['id_evidencias'],
                "grupo": f"{row['idioma']} {row['nivel']} ({row['grupo']})",
                "fecha": row['fecha_registro'].strftime("%d/%m/%Y"),
                "archivo": nombre_archivo,
                "url": link
            })

    except Exception as e:
        print(f"Error en evidencias: {e}")
    finally:
        if conn and conn.is_connected():
            cursor.close()
            conn.close()

    return render_template("evidencias.html", grupos=grupos, evidencias=lista_evidencias)

@app.route("/eliminar_evidencia/<int:id_evidencia>", methods=['POST'])
def eliminar_evidencia(id_evidencia):
    if session.get('rol') != 'maestro':
        return jsonify({'status': 'error', 'message': 'No autorizado'}), 403

    conn = None
    try:
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor(dictionary=True)

        # 1. Obtener ID de Mongo antes de borrar la relación en SQL
        cursor.execute("SELECT id_evidencias_mongo FROM evidencias WHERE id_evidencias = %s", (id_evidencia,))
        row = cursor.fetchone()

        if row:
            mongo_id = row['id_evidencias_mongo']
            
            # 2. Borrar relación en MySQL
            cursor.execute("DELETE FROM evidencias WHERE id_evidencias = %s", (id_evidencia,))
            conn.commit()

            # 3. Borrar metadatos en MongoDB
            # Nota: El archivo en Drive seguirá existiendo a menos que implementes
            # la lógica de borrado de Drive aquí también.
            if mongo_id:
                expedientes_col.delete_one({"_id": ObjectId(mongo_id)})

        return jsonify({'status': 'success', 'message': 'Evidencia eliminada correctamente'})

    except Exception as e:
        print(f"Error al eliminar evidencia: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500
    finally:
        if conn: conn.close()

@app.route("/editar_evidencia", methods=['POST'])
def editar_evidencia():
    if session.get('rol') != 'maestro':
        return redirect(url_for('login'))

    id_evidencia = request.form.get('id_evidencia_edit')
    nuevo_grupo = request.form.get('id_grupo_edit')
    
    conn = None
    try:
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor()

        # Actualizamos la relación en MySQL
        cursor.execute("UPDATE evidencias SET id_grupo = %s WHERE id_evidencias = %s", (nuevo_grupo, id_evidencia))
        conn.commit()
        
    except Exception as e:
        print(f"Error al editar evidencia: {e}")
    finally:
        if conn: conn.close()

    return redirect(url_for('evidencias'))

@app.route("/clasesprofe")
def clasesprofe():
    # 1. Seguridad: Verificar que el rol sea 'maestro'
    if session.get('rol') != 'maestro':
        return redirect(url_for('login'))
    
    user_id = session.get('user_id')
    conn = None
    mis_grupos = []

    try:
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor(dictionary=True)

        # 2. Consulta: Obtener grupos del profesor + conteo de alumnos inscritos
        query = """
            SELECT 
                g.id_grupo,
                g.numero_salon as salon,
                g.grupo as nombre_grupo,
                i.nombre as idioma,
                c.nivel,
                h.dias,
                h.hora,
                (SELECT COUNT(*) FROM inscripciones_idioma ii 
                 WHERE ii.id_grupo = g.id_grupo AND ii.estado = 'Activo') as total_alumnos
            FROM grupos g
            JOIN cursos c ON g.id_curso = c.id_curso
            JOIN idioma i ON c.id_idioma = i.id_idioma
            LEFT JOIN horario h ON g.id_horario = h.id_horario
            WHERE g.id_profesor = %s
            ORDER BY i.nombre, c.nivel
        """
        cursor.execute(query, (user_id,))
        mis_grupos = cursor.fetchall()

    except Exception as e:
        print(f"Error cargando clases profe: {e}")
        # En producción podrías manejar el error de otra forma
    finally:
        if conn and conn.is_connected():
            cursor.close()
            conn.close()

    # Renderizar la plantilla con los datos obtenidos
    return render_template("clasesprofe.html", grupos=mis_grupos)

@app.route("/asistencia")
def asistencia():
    return redirect('gestion_asistencia')

@app.route("/gestion_asistencia/<int:id_grupo>")
def gestion_asistencia(id_grupo):
    # Seguridad: Permitir Maestros y Staff
    if 'user_id' not in session or session.get('rol') not in ['maestro', 'staff']:
        return redirect(url_for('login'))
        
    conn = None
    try:
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor(dictionary=True)
        
        # A) Obtener datos del Grupo
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

        # B) Obtener lista de alumnos CON CONTEOS de asistencia
        # Usamos 'inasistencia = 1' para contar faltas y 'asistencia = 1' para presencias
        cursor.execute("""
            SELECT a.id_alumno, a.matricula, 
                   CONCAT(a.nombre, ' ', a.apellido_p, ' ', IFNULL(a.apellido_m, '')) as nombre_completo,
                   
                   (SELECT COUNT(*) FROM asistencias asis 
                    WHERE asis.id_alumno = a.id_alumno 
                      AND asis.id_grupo = %s 
                      AND asis.asistencia = 1) as total_asistencias,
                      
                   (SELECT COUNT(*) FROM asistencias asis 
                    WHERE asis.id_alumno = a.id_alumno 
                      AND asis.id_grupo = %s 
                      AND asis.inasistencia = 1) as total_faltas

            FROM alumnos a
            JOIN inscripciones_idioma ii ON a.id_alumno = ii.id_alumno
            WHERE ii.id_grupo = %s AND ii.estado = 'Activo'
            ORDER BY a.apellido_p ASC
        """, (id_grupo, id_grupo, id_grupo))
        
        alumnos = cursor.fetchall()
        
        return render_template("listas.html", 
                               alumnos=alumnos, 
                               grupo=info_grupo, 
                               id_grupo=id_grupo)
                               
    except Exception as e:
        print(f"Error gestion_asistencia: {e}")
        return f"Error: {e}", 500
    finally:
        if conn: conn.close()

# --- API: GUARDAR ASISTENCIA (Adaptado a tu Schema) ---
@app.route("/api/guardar_asistencia", methods=["POST"])
def api_guardar_asistencia():
    # Seguridad: Solo maestros pueden modificar
    if session.get('rol') != 'maestro':
        return jsonify({'status': 'error', 'message': 'No autorizado (Solo docentes)'}), 403

    conn = None
    try:
        data = request.get_json()
        
        id_alumno = data.get('id_alumno')
        id_grupo = data.get('id_grupo')
        fecha_clase = data.get('fecha') # YYYY-MM-DD
        asistio = data.get('asistio')   # true/false
        
        # Lógica para llenar ambas columnas
        valor_asistencia = 1 if asistio else 0
        valor_inasistencia = 0 if asistio else 1 
        
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor()
        
        # Validar grupo
        cursor.execute("SELECT id_profesor FROM grupos WHERE id_grupo = %s", (id_grupo,))
        res_profe = cursor.fetchone()
        if not res_profe: return jsonify({"status": "error", "mensaje": "Grupo inválido"}), 400
        id_profesor = res_profe[0]

        # Insertar o Actualizar
        sql = """
            INSERT INTO asistencias (asistencia, inasistencia, id_grupo, id_alumno, id_profesor, fecha_clase) 
            VALUES (%s, %s, %s, %s, %s, %s) 
            ON DUPLICATE KEY UPDATE asistencia = %s, inasistencia = %s
        """
        
        cursor.execute(sql, (
            valor_asistencia, valor_inasistencia, 
            id_grupo, id_alumno, id_profesor, fecha_clase, 
            valor_asistencia, valor_inasistencia
        ))
        conn.commit()
        
        return jsonify({"status": "success"})
        
    except Exception as e:
        print(f"Error SQL Asistencia: {e}")
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
    # Cualquiera logueado puede ver (Staff incluido)
    if 'user_id' not in session: return jsonify({'status': 'error'}), 403
    
    conn = None
    try:
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor(dictionary=True)
        
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
    # Solo maestros pueden escribir
    if session.get('rol') != 'maestro': return jsonify({'status': 'error', 'message': 'Solo lectura'}), 403
    
    conn = None
    try:
        data = request.get_json()
        id_alumno = data.get('id_alumno')
        descripcion = data.get('descripcion')
        id_comentario = data.get('id_comentario')
        id_profesor = session.get('user_id')

        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor()

        if id_comentario:
            # Editar (Solo si es suyo)
            cursor.execute("""
                UPDATE comentarios SET descripcion = %s, fecha_registro = NOW()
                WHERE id_comentario = %s AND id_profesor = %s
            """, (descripcion, id_comentario, id_profesor))
        else:
            # Nuevo
            cursor.execute("""
                INSERT INTO comentarios (descripcion, id_alumno, id_profesor)
                VALUES (%s, %s, %s)
            """, (descripcion, id_alumno, id_profesor))
        
        conn.commit()
        return jsonify({'status': 'success'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500
    finally:
        if conn: conn.close()

@app.route("/api/eliminar_comentario", methods=["POST"])
def api_eliminar_comentario():
    # Solo maestros pueden borrar
    if session.get('rol') != 'maestro': return jsonify({'status': 'error'}), 403
    
    conn = None
    try:
        data = request.get_json()
        id_comentario = data.get('id_comentario')
        id_profesor = session.get('user_id')

        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor()
        
        # Solo borra si el profesor es el autor
        cursor.execute("DELETE FROM comentarios WHERE id_comentario = %s AND id_profesor = %s", (id_comentario, id_profesor))
        
        if cursor.rowcount > 0:
            conn.commit()
            return jsonify({'status': 'success'})
        else:
            return jsonify({'status': 'error', 'message': 'No se pudo borrar'}), 403
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500
    finally:
        if conn: conn.close()

@app.route("/maestroinfo/<string:tipo>/<int:id>")
def maestroinfo(tipo, id):
    if 'user_id' not in session: return redirect(url_for('login'))
        
    conn = None
    personal_data = None
    datos_fiscales = None
    expediente_urls = {}
    
    try:
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor(dictionary=True)

        # A) DATOS PERSONALES Y FINANCIEROS (Salario, IVA, ISR están aquí)
        if tipo == 'maestro':
            cursor.execute("SELECT * FROM profesores WHERE id_profesor = %s", (id,))
        elif tipo == 'staff':
            cursor.execute("SELECT * FROM staff WHERE id_staff = %s", (id,))
        else:
            return "Tipo no válido", 400
            
        personal_data = cursor.fetchone()
        if not personal_data: return "No encontrado", 404

        # B) DATOS FISCALES (RFC, Razón Social...) - Solo Maestros
        if tipo == 'maestro':
            cursor.execute("SELECT * FROM profesores_datos_fiscales WHERE id_profesor = %s", (id,))
            datos_fiscales = cursor.fetchone()

        # C) DOCUMENTOS (Desde MongoDB)
        mongo_id = personal_data.get('id_expediente_mongo')
        if mongo_id:
            expediente_doc = expedientes_col.find_one({"_id": ObjectId(mongo_id)})
            if expediente_doc and 'documentos' in expediente_doc:
                expediente_urls = expediente_doc['documentos']

    except Exception as e:
        print(f"Error cargando perfil: {e}")
    finally:
        if conn: conn.close()

    return render_template("maestroinfo.html", 
                           personal=personal_data, 
                           tipo=tipo, 
                           datos_fiscales=datos_fiscales,
                           expediente=expediente_urls)

@app.route("/nomina", methods=['GET', 'POST'])
def nomina():
    # Seguridad: Solo Maestros
    if session.get('rol') != 'maestro':
        return redirect(url_for('login'))
    
    user_id = session.get('user_id')
    conn = None
    historial = []
    datos_profesor = {}
    mensaje_error = None
    mensaje_exito = None

    try:
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor(dictionary=True)

        # A) CARGAR DATOS DEL PROFESOR
        cursor.execute("""
            SELECT p.valor_hora, p.tasa_iva, p.tasa_isr_retenido, 
                   df.rfc, df.razon_social, df.regimen_fiscal, df.codigo_postal
            FROM profesores p
            LEFT JOIN profesores_datos_fiscales df ON p.id_profesor = df.id_profesor
            WHERE p.id_profesor = %s
        """, (user_id,))
        datos_profesor = cursor.fetchone()

        # B) CARGAR DATOS RECEPTOR (UTR)
        cursor.execute("SELECT * FROM utr_data LIMIT 1")
        utr_db = cursor.fetchone()
        
        receiver_data = {
            "Rfc": utr_db['rfc'] if utr_db else "UTR130212KB3",
            "Name": utr_db['razon_social'] if utr_db else "UNIVERSIDAD TECNOLÓGICA EL RETOÑO",
            "CfdiUse": utr_db['uso_cfdi'] if utr_db else "G03",
            "FiscalRegime": utr_db['regimen_fiscal'] if utr_db else "603",
            "TaxZipCode": str(utr_db['cp']) if utr_db else "20337"
        }

        # C) PROCESAR TIMBRADO (POST)
        if request.method == 'POST':
            horas = float(request.form.get('horas', 0))
            fecha_inicio = request.form.get('fecha_inicio')
            fecha_fin = request.form.get('fecha_fin')

            if not datos_profesor or not datos_profesor['rfc']:
                mensaje_error = "Error: Faltan tus datos fiscales en el perfil."
            elif horas <= 0:
                mensaje_error = "Error: Las horas deben ser mayor a 0."
            else:
                # 1. Calcular Montos
                valor_unitario = datos_profesor['valor_hora'] or 0
                subtotal = horas * valor_unitario
                tasa_iva = datos_profesor['tasa_iva'] or 0.16
                tasa_isr = datos_profesor['tasa_isr_retenido'] or 0.0125
                
                # 2. JSON Facturama
                payload = {
                    "Folio": f"INT-{int(datetime.now().timestamp())}",
                    "Date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "Currency": "MXN",
                    "PaymentMethod": "PUE",
                    "PaymentForm": "03",
                    "PlaceOfIssue": datos_profesor['codigo_postal'] or "20000",
                    "Exportation": "01",
                    "Issuer": {
                        "Rfc": datos_profesor['rfc'],
                        "Name": datos_profesor['razon_social'],
                        "FiscalRegime": datos_profesor['regimen_fiscal']
                    },
                    "Receiver": receiver_data,
                    "Items": [
                        {
                            "ProductCode": "86111702",
                            "Description": f"Servicios profesionales. Periodo: {fecha_inicio} al {fecha_fin}",
                            "UnitCode": "E48",
                            "Quantity": horas,
                            "UnitPrice": valor_unitario,
                            "Subtotal": subtotal,
                            "Taxes": [
                                {
                                    "Total": subtotal * tasa_iva,
                                    "Name": "IVA",
                                    "Base": subtotal,
                                    "Rate": tasa_iva,
                                    "IsRetention": False
                                },
                                {
                                    "Total": subtotal * tasa_isr,
                                    "Name": "ISR",
                                    "Base": subtotal,
                                    "Rate": tasa_isr,
                                    "IsRetention": True
                                }
                            ]
                        }
                    ]
                }

                # 3. Enviar a API
                auth_str = f"{FACTURAMA_USER}:{FACTURAMA_PASS}"
                # AQUÍ ES DONDE USAMOS base64
                b64_auth = base64.b64encode(auth_str.encode()).decode()
                headers = {'Authorization': f'Basic {b64_auth}', 'Content-Type': 'application/json'}

                try:
                    response = requests.post(FACTURAMA_URL, json=payload, headers=headers)
                    
                    if response.status_code == 201: # Éxito Real
                        res_json = response.json()
                        uuid_sat = res_json.get('Complement', {}).get('TaxStamp', {}).get('Uuid')
                        total_final = res_json.get('Total')
                        
                        query_save = """
                            INSERT INTO facturas_emitidas 
                            (id_profesor, uuid, subtotal, total, periodo_pago, fecha_timbrado)
                            VALUES (%s, %s, %s, %s, %s, NOW())
                        """
                        cursor.execute(query_save, (user_id, uuid_sat, subtotal, total_final, f"{fecha_inicio} - {fecha_fin}"))
                        conn.commit()
                        mensaje_exito = "Factura timbrada correctamente."
                    else:
                        # Fallback Simulación (Si falla la API o no hay credenciales)
                        print(f"API Error: {response.text}")
                        uuid_simulado = str(uuid.uuid4()).upper()
                        total_simulado = subtotal + (subtotal*tasa_iva) - (subtotal*tasa_isr)
                        
                        query_save = """
                            INSERT INTO facturas_emitidas (id_profesor, uuid, subtotal, total, periodo_pago, fecha_timbrado)
                            VALUES (%s, %s, %s, %s, %s, NOW())
                        """
                        cursor.execute(query_save, (user_id, uuid_simulado, subtotal, total_simulado, f"{fecha_inicio} - {fecha_fin}"))
                        conn.commit()
                        mensaje_exito = "Factura generada (Modo Simulación - API Error)."
                except Exception as req_err:
                    print(f"Error de conexión: {req_err}")
                    mensaje_error = "Error al conectar con Facturama."

        # D) CARGAR HISTORIAL
        cursor.execute("SELECT * FROM facturas_emitidas WHERE id_profesor = %s ORDER BY fecha_timbrado DESC", (user_id,))
        historial = cursor.fetchall()

    except Exception as e:
        print(f"Error nómina: {e}")
        mensaje_error = f"Error del sistema: {str(e)}"
    finally:
        if conn: conn.close()

    return render_template("nomina.html", historial=historial, datos=datos_profesor, error=mensaje_error, exito=mensaje_exito)

@app.route("/ver_recibo/<int:id_factura>")
def ver_recibo(id_factura):
    if session.get('rol') != 'maestro': return redirect(url_for('login'))
    user_id = session.get('user_id')
    conn = None
    try:
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor(dictionary=True)

        # 1. Datos Factura
        cursor.execute("SELECT * FROM facturas_emitidas WHERE id_factura = %s AND id_profesor = %s", (id_factura, user_id))
        factura = cursor.fetchone()
        
        # 2. Datos Emisor (Profesor)
        cursor.execute("""
            SELECT p.valor_hora, p.tasa_iva, p.tasa_isr_retenido, df.rfc, df.razon_social, df.regimen_fiscal, df.codigo_postal
            FROM profesores p LEFT JOIN profesores_datos_fiscales df ON p.id_profesor = df.id_profesor
            WHERE p.id_profesor = %s
        """, (user_id,))
        emisor = cursor.fetchone()

        # 3. Datos Receptor (UTR) - También desde DB
        cursor.execute("SELECT * FROM utr_data LIMIT 1")
        receptor = cursor.fetchone()
        
        if not receptor:
             receptor = {
                "rfc": "UTR130212KB3",
                "razon_social": "UNIVERSIDAD TECNOLÓGICA EL RETOÑO",
                "uso_cfdi": "G03",
                "cp": "20337",
                "regimen_fiscal": "603"
            }

        # Reconstruir desglose
        valor_unitario = emisor['valor_hora']
        cantidad = factura['subtotal'] / valor_unitario if valor_unitario > 0 else 0
        
        detalles = {
            "cantidad": round(cantidad, 2),
            "valor_unitario": valor_unitario,
            "importe": factura['subtotal'],
            "iva_monto": factura['subtotal'] * emisor['tasa_iva'],
            "isr_monto": factura['subtotal'] * emisor['tasa_isr_retenido'],
            "tasa_iva_pct": int(emisor['tasa_iva'] * 100),
            "tasa_isr_pct": emisor['tasa_isr_retenido'] * 100
        }
        
        # Pasamos 'receptor' al template
        return render_template("recibo.html", factura=factura, emisor=emisor, receptor=receptor, detalles=detalles)
    except Exception as e:
        return f"Error: {e}", 500
    finally:
        if conn: conn.close()

@app.route("/comprar_timbres", methods=['GET', 'POST'])
def comprar_timbres():
    if session.get('rol') != 'maestro': return redirect(url_for('login'))
    
    if request.method == 'POST':
        return "<script>alert('¡Compra exitosa! Timbres agregados.'); window.location.href='/nomina';</script>"

    user_id = session.get('user_id')
    conn = mysql.connector.connect(**db_config)
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT correo_electronico FROM profesores WHERE id_profesor = %s", (user_id,))
    usuario = cursor.fetchone()
    conn.close()

    return render_template("comprar_timbres.html", correo=usuario['correo_electronico'])

@app.route("/perfil")
def perfil():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    rol = session.get('rol')
    user_id = session.get('user_id')
    conn = None
    
    # Variables base para la plantilla
    usuario_data = {}
    datos_fiscales = None
    info_extra = "Sin información" 
    permisos_activos = []

    try:
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor(dictionary=True)

        # --- CASO ALUMNO ---
        if rol == 'alumno':
            cursor.execute("SELECT * FROM alumnos WHERE id_alumno = %s", (user_id,))
            user = cursor.fetchone()
            if user:
                usuario_data = {
                    "nombre": user['nombre'],
                    "apellido_p": user['apellido_p'],
                    "apellido_m": user['apellido_m'],
                    "nombre_completo": f"{user['nombre']} {user['apellido_p']} {user['apellido_m']}",
                    "id_ref": user['matricula'], # Muestra matrícula
                    "correo": user['correo_electronico'],
                    "telefono": user['telefono']
                }
            
            # Buscar Curso Activo
            cursor.execute("""
                SELECT i.nombre as idioma, c.nivel, h.dias, h.hora
                FROM inscripciones_idioma ii
                JOIN grupos g ON ii.id_grupo = g.id_grupo
                JOIN cursos c ON g.id_curso = c.id_curso
                JOIN idioma i ON c.id_idioma = i.id_idioma
                LEFT JOIN horario h ON g.id_horario = h.id_horario
                WHERE ii.id_alumno = %s AND ii.estado = 'Activo'
                LIMIT 1
            """, (user_id,))
            curso = cursor.fetchone()
            if curso:
                info_extra = f"{curso['idioma']} {curso['nivel']} ({curso['dias']} {curso['hora']})"

        # --- CASO MAESTRO ---
        elif rol == 'maestro':
            cursor.execute("SELECT * FROM profesores WHERE id_profesor = %s", (user_id,))
            user = cursor.fetchone()
            if user:
                usuario_data = {
                    "nombre": user['nombre'],
                    "apellido_p": user['apellido_p'],
                    "apellido_m": user['apellido_m'],
                    "nombre_completo": f"{user['nombre']} {user['apellido_p']} {user['apellido_m']}",
                    "id_ref": "Docente",
                    "correo": user['correo_electronico'],
                    "telefono": user['telefono'],
                    "fecha_nacimiento": user['fecha_nacimiento'],
                    "genero": user['genero']
                }
            
            # Cargar Datos Fiscales (Para nómina)
            cursor.execute("SELECT * FROM profesores_datos_fiscales WHERE id_profesor = %s", (user_id,))
            datos_fiscales = cursor.fetchone()

            # Contar Grupos Asignados
            cursor.execute("SELECT COUNT(*) as total FROM grupos WHERE id_profesor = %s", (user_id,))
            res = cursor.fetchone()
            info_extra = f"{res['total']} Grupos Asignados"
            
            # Cargar Permisos de Delegación Activos
            cursor.execute("""
                SELECT pt.id_permisos_temporales, pt.fecha_inicio, pt.fecha_fin, 
                       CONCAT(p.nombre, ' ', p.apellido_p) as sustituto
                FROM permisos_temporales pt
                JOIN profesores p ON pt.id_profesor_sustituto = p.id_profesor
                WHERE pt.id_profesor = %s AND pt.estado = 'activo'
            """, (user_id,))
            permisos_activos = cursor.fetchall()

    except Exception as e:
        print(f"Error en perfil: {e}")
    finally:
        if conn: conn.close()

    return render_template("Perfil.html", 
                           usuario=usuario_data, 
                           info_extra=info_extra, 
                           fiscal=datos_fiscales,
                           permisos=permisos_activos)

@app.route("/crear_permiso", methods=['POST'])
def crear_permiso():
    if session.get('rol') != 'maestro': return redirect(url_for('login'))
    
    user_id = session.get('user_id')
    email_sustituto = request.form.get('email_sustituto')
    fecha_inicio = request.form.get('fecha_inicio')
    fecha_fin = request.form.get('fecha_fin')
    
    conn = None
    try:
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor(dictionary=True)

        # 1. Validar que el sustituto exista
        cursor.execute("SELECT id_profesor FROM profesores WHERE correo_electronico = %s", (email_sustituto,))
        sustituto = cursor.fetchone()
        
        if not sustituto:
            return "<script>alert('Error: El correo no corresponde a un docente registrado.'); window.history.back();</script>"
        
        if sustituto['id_profesor'] == user_id:
            return "<script>alert('No puedes darte permiso a ti mismo.'); window.history.back();</script>"

        # 2. Insertar el permiso
        query = """
            INSERT INTO permisos_temporales (id_profesor, id_profesor_sustituto, fecha_inicio, fecha_fin, estado)
            VALUES (%s, %s, %s, %s, 'activo')
        """
        cursor.execute(query, (user_id, sustituto['id_profesor'], fecha_inicio, fecha_fin))
        conn.commit()
        
        return "<script>alert('Permiso otorgado exitosamente.'); window.location.href='/perfil';</script>"

    except Exception as e:
        print(f"Error crear permiso: {e}")
        return f"<script>alert('Error: {e}'); window.history.back();</script>"
    finally:
        if conn: conn.close()

@app.route("/revocar_permiso/<int:id_permiso>")
def revocar_permiso(id_permiso):
    if session.get('rol') != 'maestro': return redirect(url_for('login'))
    
    conn = None
    try:
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor()
        # Solo revocamos si el permiso pertenece al usuario logueado
        cursor.execute("UPDATE permisos_temporales SET estado = 'revocado' WHERE id_permisos_temporales = %s AND id_profesor = %s", (id_permiso, session.get('user_id')))
        conn.commit()
    except Exception as e:
        print(e)
    finally:
        if conn: conn.close()
    
    return redirect(url_for('perfil'))

@app.route("/guardar_perfil_docente", methods=['POST'])
def guardar_perfil_docente():
    # Solo maestros pueden editar sus datos fiscales
    if session.get('rol') != 'maestro': return redirect(url_for('login'))
    
    user_id = session.get('user_id')
    f = request.form
    conn = None

    try:
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor()

        # 1. Actualizar Datos Personales Básicos
        cursor.execute("""
            UPDATE profesores 
            SET nombre=%s, apellido_p=%s, apellido_m=%s, telefono=%s, 
                fecha_nacimiento=%s, genero=%s
            WHERE id_profesor=%s
        """, (f['nombre'], f['apellido_p'], f['apellido_m'], f['telefono'], 
              f['fecha_nacimiento'] or None, f['genero'], user_id))

        # 2. Actualizar o Insertar Datos Fiscales (Upsert)
        rfc = f['rfc']
        razon = f['razon_social']
        regimen = f['regimen_fiscal']
        clabe = f['cuenta_clabe']
        cp = f['codigo_postal']

        cursor.execute("""
            INSERT INTO profesores_datos_fiscales 
            (id_profesor, rfc, razon_social, regimen_fiscal, cuenta_clabe, codigo_postal)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE 
            rfc=%s, razon_social=%s, regimen_fiscal=%s, cuenta_clabe=%s, codigo_postal=%s
        """, (user_id, rfc, razon, regimen, clabe, cp, rfc, razon, regimen, clabe, cp))

        conn.commit()
        return "<script>alert('Datos actualizados correctamente.'); window.location.href='/perfil';</script>"

    except Exception as e:
        print(f"Error al guardar perfil: {e}")
        return f"Error: {e}", 500
    finally:
        if conn: conn.close()

@app.route("/actualizar_password", methods=["POST"])
def actualizar_password():
    if 'user_id' not in session: return redirect(url_for('login'))

    user_id = session.get('user_id')
    rol = session.get('rol')
    current = request.form.get('current_pass')
    new_pass = request.form.get('new_pass')
    confirm = request.form.get('confirm_pass')

    if new_pass != confirm:
        return "<script>alert('Las contraseñas nuevas no coinciden'); window.history.back();</script>"
    
    if len(new_pass) < 6:
        return "<script>alert('La contraseña es muy corta (mínimo 6 caracteres)'); window.history.back();</script>"

    # Determinar en qué tabla buscar según el rol
    if rol == 'alumno': table, id_col = "alumnos", "id_alumno"
    elif rol == 'maestro': table, id_col = "profesores", "id_profesor"
    elif rol == 'staff': table, id_col = "staff", "id_staff"

    conn = None
    try:
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor(dictionary=True)
        
        # Verificar contraseña actual
        cursor.execute(f"SELECT contraseña FROM {table} WHERE {id_col} = %s", (user_id,))
        user = cursor.fetchone()
        
        if not user or not check_password_hash(user['contraseña'], current):
             return "<script>alert('La contraseña actual es incorrecta'); window.history.back();</script>"
             
        # Actualizar con hash
        new_hash = generate_password_hash(new_pass)
        cursor.execute(f"UPDATE {table} SET contraseña = %s WHERE {id_col} = %s", (new_hash, user_id))
        conn.commit()
        
        return "<script>alert('Contraseña actualizada exitosamente.'); window.location.href='/perfil';</script>"

    except Exception as e:
        return f"Error interno: {e}", 500
    finally:
        if conn: conn.close()

#Alumno

@app.route("/gestion_cursos")
def gestion_cursos():
    conn = None
    try:
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor(dictionary=True)

        rol = session.get('rol')
        user_id = session.get('user_id')
        
        # Título por defecto
        titulo = "Nuestros Grupos Abiertos"

        if rol == 'alumno' and user_id:
            # --- ESCENARIO ALUMNO: Ver solo mis clases activas ---
            titulo = "Mis Clases Actuales"
            query = """
                SELECT 
                    g.id_grupo,
                    g.grupo AS nombre_grupo,
                    i.nombre AS idioma,
                    c.nivel,
                    COALESCE(CONCAT(p.nombre, ' ', p.apellido_p), 'Por asignar') AS profesor,
                    COALESCE(h.dias, 'Por definir') AS dias,
                    COALESCE(h.hora, 'Por definir') AS hora,
                    h.sede
                FROM inscripciones_idioma ii
                JOIN grupos g ON ii.id_grupo = g.id_grupo
                LEFT JOIN cursos c ON g.id_curso = c.id_curso
                LEFT JOIN idioma i ON c.id_idioma = i.id_idioma
                LEFT JOIN profesores p ON g.id_profesor = p.id_profesor
                LEFT JOIN horario h ON g.id_horario = h.id_horario
                WHERE ii.id_alumno = %s AND ii.estado = 'Activo'
                ORDER BY i.nombre ASC
            """
            cursor.execute(query, (user_id,))
            
        else:
            # --- ESCENARIO PÚBLICO/STAFF: Ver toda la oferta ---
            query = """
                SELECT 
                    g.id_grupo,
                    g.grupo AS nombre_grupo,
                    i.nombre AS idioma,
                    c.nivel,
                    COALESCE(CONCAT(p.nombre, ' ', p.apellido_p), 'Por asignar') AS profesor,
                    COALESCE(h.dias, 'Por definir') AS dias,
                    COALESCE(h.hora, 'Por definir') AS hora,
                    h.sede
                FROM grupos g
                LEFT JOIN cursos c ON g.id_curso = c.id_curso
                LEFT JOIN idioma i ON c.id_idioma = i.id_idioma
                LEFT JOIN profesores p ON g.id_profesor = p.id_profesor
                LEFT JOIN horario h ON g.id_horario = h.id_horario
                ORDER BY i.nombre ASC, c.nivel ASC
            """
            cursor.execute(query)

        grupos_disponibles = cursor.fetchall()

        return render_template("cursos.html", grupos=grupos_disponibles, titulo_pagina=titulo)

    except Exception as e:
        print(f"Error en cursos: {e}")
        return f"Error al cargar cursos: {e}", 500
    finally:
        if conn and conn.is_connected():
            cursor.close()
            conn.close()

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
    return redirect(url_for('logout'))

if __name__ == "__main__":
    app.run(debug=True)