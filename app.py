
from flask import Flask, render_template, request, abort, redirect, url_for, Response, jsonify, session
import yagmail
import mysql.connector
from pymongo import MongoClient
from bson import ObjectId
from datetime import datetime, timedelta
import os
import uuid
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename
import json
from dotenv import load_dotenv
import secrets
import string
import threading
from io import BytesIO 
from gridfs import GridFS
import locale

load_dotenv()

app = Flask(__name__)

app.config['SECRET_KEY'] = os.getenv('SECRET_KEY')
if not app.config['SECRET_KEY']:
    raise ValueError("No se encontró SECRET_KEY. Define la variable de entorno.")

# --- Filtros y Context Processors ---
def format_currency_mxn(value):
    if value is None:
        return "0.00"
    try:
        # Usa el método de la cadena para dar formato de moneda MXN
        return f"{float(value):,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")
    except (TypeError, ValueError):
        return str(value)

app.jinja_env.filters['format_currency'] = format_currency_mxn

@app.context_processor
def inject_now():
    return {'now': datetime.utcnow()}

# --- Configuración de Conexiones ---
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

# =================================================================
# === CONFIGURACIONES Y FUNCIONES AUXILIARES ===
# =================================================================

UTR_DATA = {
    "rfc": "UTR130212KB3",
    "razon_social": "UNIVERSIDAD TECNOLOGICA EL RETOÑO",
    "cp": "20337",
    "regimen_fiscal": "603 - Personas Morales con Fines No Lucrativos",
    "uso_cfdi": "G03 - Gastos en general",
    "metodo_pago": "PUE - Pago en una sola exhibición",
    "forma_pago": "03 - Transferencia electrónica"
}
VALOR_HORA = 105.00 # MXN - Valor unitario de la hora
COSTO_REINSCRIPCION_BASE = 1870.00 # MXN - Costo base de reinscripción

def calcular_impuestos(horas_trabajadas):
    """Calcula Subtotal, IVA, Retenciones e Importe Neto, asumiendo RESICO."""
    
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

def process_personal_registration_async(id_personal, tipo_personal, email, contrasena_temporal, uploaded_files_data, nombre, apellido_p, apellido_m):
    """
    Función que se ejecuta en un hilo separado para manejar tareas pesadas:
    subida de archivos a GridFS, actualización de MySQL y envío de correos.
    """
    
    conn_async = None
    cursor_async = None
    
    # Necesitamos recrear la conexión de yagmail en este hilo si queremos usarla
    try:
        YAG_USER = os.getenv('YAG_USER')
        YAG_TOKEN = os.getenv('YAG_TOKEN')
        yag_async = yagmail.SMTP(YAG_USER, YAG_TOKEN)
    except Exception as e:
        print(f"Error al inicializar yagmail en hilo: {e}")
        yag_async = None
    
    try:
        # --- A. SUBIR ARCHIVOS A GRIDFS Y CONSTRUIR EXPEDIENTE ---
        documentos_mongo = {}
        
        for mongo_key, file_content, original_filename, content_type in uploaded_files_data:
            file_stream = BytesIO(file_content) 
            
            # Subir archivo a GridFS
            grid_fs_id = fs.put(
                file_stream, 
                filename=original_filename,
                content_type=content_type,
                alias=mongo_key,
                usuario_registro=email,
                tipo_personal=tipo_personal
            )
            documentos_mongo[mongo_key] = str(grid_fs_id) 

        # --- B. GUARDAR EXPEDIENTE EN MONGODB Y ACTUALIZAR MYSQL ---
        expediente_doc = {
            "tipo": tipo_personal, 
            "id_relacional": id_personal,
            "documentos": documentos_mongo, 
            "metadata": { "fecha_subida": datetime.utcnow(), "actualizado_por": "sistema_admin_async" }
        }
        mongo_id = expedientes_col.insert_one(expediente_doc).inserted_id
        
        # Reconexión a MySQL para la actualización final
        conn_async = mysql.connector.connect(**db_config)
        cursor_async = conn_async.cursor()
        
        table_name = "profesores" if tipo_personal == 'maestro' else "staff"
        id_column = "id_profesor" if tipo_personal == 'maestro' else "id_staff"
        
        update_query = f"UPDATE {table_name} SET id_expediente_mongo = %s WHERE {id_column} = %s"
        cursor_async.execute(update_query, (str(mongo_id), id_personal))
        conn_async.commit()
        
        # --- C. ENVÍO DE CORREO (LENTO) ---
        if yag_async:
            nombre_completo = f"{nombre} {apellido_p} {apellido_m}".strip()
            # Usar un contexto de aplicación para generar url_for, o usar URL codificada
            with app.app_context():
                portal_url = url_for('login', _external=True) 
            
            subject = f"¡Bienvenido/a {nombre} al Centro de Idiomas UTR - Portal de {tipo_personal.capitalize()}!"
            
            # Estructura del correo en HTML
            html_body = f"""
                <html>
                <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
                    <div style="max-width: 600px; margin: 20px auto; padding: 20px; border: 1px solid #ddd; border-radius: 10px;">
                        <h2 style="color: #007bff; border-bottom: 2px solid #eee; padding-bottom: 10px;">
                            ¡Bienvenido/a {nombre_completo}!
                        </h2>
                        <p>Te damos la más cordial bienvenida al equipo del Centro de Idiomas UTR como <b>{tipo_personal.capitalize()}</b>.</p>
                        <p>Tu cuenta ha sido creada y tus documentos se han subido exitosamente a tu expediente digital. En breve podrás acceder a tu portal.</p>
                        
                        <h3 style="color: #28a745;">Tus Credenciales de Acceso:</h3>
                        <div style="background-color: #f8f9fa; padding: 15px; border-radius: 5px; border-left: 5px solid #28a745;">
                            <p><strong>Portal de Acceso:</strong> <a href="{portal_url}" style="color: #007bff; text-decoration: none;">Acceder al Sistema CIUTR</a></p>
                            <p><strong>Usuario (Correo):</strong> <code>{email}</code></p>
                            <p><strong>Contraseña TEMPORAL:</strong> <strong style="font-size: 1.1em; color: #dc3545;">{contrasena_temporal}</strong></p>
                        </div>
                        
                        <p><strong>Importante:</strong> Por seguridad, te recomendamos **cambiar tu contraseña inmediatamente** después de tu primer inicio de sesión.</p>
                        <p>Si tienes alguna duda o necesitas asistencia, no dudes en contactar al equipo de administración.</p>
                        <p>Atentamente,<br>Equipo de Administración CIUTR</p>
                    </div>
                </body>
                </html>
            """
            
            yag_async.send(to=email, subject=subject, contents=[html_body])

            logs_col.insert_one({
                "tipo_entidad": "sistema",
                "id_entidad": id_personal,
                "accion": "correo_bienvenida_enviado_async",
                "detalle": f"Correo de bienvenida HTML enviado con credenciales y expediente subido.", 
                "usuario": "sistema_auto_async", 
                "fecha": datetime.utcnow()
            })
            
        print(f"INFO: Registro asíncrono de {tipo_personal} ID {id_personal} completado con éxito.")
        
    except Exception as e:
        print(f"ERROR ASÍNCRONO al procesar el registro de {tipo_personal} ID {id_personal}: {e}")
        logs_col.insert_one({
            "tipo_entidad": tipo_personal,
            "id_entidad": id_personal,
            "accion": "error_registro_async",
            "detalle": f"Fallo en la tarea asíncrona (Subida/Correo). Error: {e}",
            "usuario": "sistema_auto_async", 
            "fecha": datetime.utcnow()
        })
        if conn_async: conn_async.rollback()
        
    finally:
        if 'cursor_async' in locals() and cursor_async: cursor_async.close()
        if conn_async and conn_async.is_connected(): conn_async.close()

# =================================================================
# === RUTAS DE DOCUMENTOS Y AUXILIARES ===
# =================================================================

@app.route('/expediente/ver/<string:mongo_id>/<string:tipo_doc>')
def ver_documento_expediente(mongo_id, tipo_doc):
    try:
        expediente = expedientes_col.find_one({"_id": ObjectId(mongo_id)})
        
        if not expediente:
            abort(404, description="Expediente no encontrado en MongoDB.")

        # Obtener el ObjectId del archivo en GridFS
        grid_fs_id_str = expediente.get('documentos', {}).get(tipo_doc)
        
        if not grid_fs_id_str:
            abort(404, description=f"Referencia de documento '{tipo_doc}' no encontrada en el expediente.")

        # Obtener el archivo de GridFS
        try:
            grid_file = fs.get(ObjectId(grid_fs_id_str))
        except Exception:
            abort(404, description="Archivo no encontrado en GridFS.")

        # Devolver el archivo como una respuesta de Flask
        response = Response(
            response=grid_file.read(),
            status=200,
            mimetype=grid_file.content_type
        )
        # Permite la visualización en línea (inline)
        response.headers['Content-Disposition'] = f'inline; filename="{grid_file.filename}"'
        return response

    except Exception as e:
        print(f"Error al servir documento desde GridFS: {e}")
        abort(500, description="Error interno al acceder al documento.")


# =================================================================
# === RUTAS DE GESTIÓN DE PERSONAL (Maestros y Staff) ===
# =================================================================

@app.route("/gestion-personal")
def gestion_personal():
    """
    Obtiene la lista consolidada de Profesores y Staff, aplicando un filtro de búsqueda si existe.
    """
    conn = None
    personal = []
    # Obtener el término de búsqueda desde la URL (?q=termino)
    busqueda = request.args.get('q', '').strip() 
    
    try:
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor(dictionary=True)

        where_clause = ""
        search_params_tuple = ()

        if busqueda:
            # Si hay búsqueda, preparamos el WHERE y los parámetros
            where_clause = """
                WHERE 
                    (nombre LIKE %s OR apellido_p LIKE %s OR apellido_m LIKE %s OR correo_electronico LIKE %s)
            """
            search_param = f"%{busqueda}%"
            search_params_tuple = (search_param, search_param, search_param, search_param)

        # Función auxiliar para ejecutar y obtener datos
        def fetch_personal(table, id_col, tipo):
            query = f"""
                SELECT {id_col} AS id, nombre, apellido_p, apellido_m, genero, '{tipo}' AS tipo 
                FROM {table}
                {where_clause}
            """
            cursor.execute(query, search_params_tuple) 
            return cursor.fetchall()

        # 1. Obtener Maestros
        maestros = fetch_personal("profesores", "id_profesor", "maestro")
        
        # 2. Obtener Staff
        staff_list = fetch_personal("staff", "id_staff", "staff")
        
        # 3. Consolidar la lista
        personal = maestros + staff_list

    except mysql.connector.Error as err:
        print(f"ERROR DE BASE DE DATOS: {err}")
        
    except Exception as e:
        print(f"ERROR GENERAL al cargar personal: {e}")
        
    finally:
        if conn and conn.is_connected():
            cursor.close()
            conn.close()

    # Pasa la lista y el término de búsqueda al template
    return render_template("añadiradmin.html", personal=personal, busqueda=busqueda)
    
@app.route('/guardar-personal', methods=['POST'])
def guardar_personal():
    """
    Ruta optimizada. Guarda los datos básicos de MySQL y delega la subida de 
    documentos (GridFS) y el envío de correo (yagmail) a un hilo secundario.
    """
    conn = None
    email = request.form.get('email')
    
    # -------------------------------------------------------------
    # 1. GENERACIÓN DE CONTRASEÑA TEMPORAL SEGURA (SÍNCRONA)
    # -------------------------------------------------------------
    caracteres = string.ascii_letters + string.digits 
    contrasena_temporal = ''.join(secrets.choice(caracteres) for i in range(12))
    password_encriptada = generate_password_hash(contrasena_temporal)
    
    # Extraer la información del formulario
    form_data = {
        'nombre': request.form.get('nombre'),
        'apellidos': request.form.get('apellidos'),
        'email': email,
        'telefono': request.form.get('telefono'),
        'tipo_personal': request.form.get('tipo_personal'),
        'fecha_nacimiento': request.form.get('fecha_n') if request.form.get('fecha_n') else None,
        'genero': request.form.get('genero')
    }
    
    # Preparar datos de archivos para pasarlos al hilo. 
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
            file_content = file.read() # Capturar el contenido binario
            uploaded_files_data.append((mongo_key, file_content, secure_filename(file.filename), file.content_type))
    
    cursor = None
    
    try:
        # -------------------------------------------------------------
        # 2. INSERCIÓN EN MYSQL (RÁPIDA) - Solo datos básicos
        # -------------------------------------------------------------
        
        # Separar apellidos
        apellido_parts = form_data['apellidos'].split(' ')
        apellido_p = apellido_parts[0]
        apellido_m = ' '.join(apellido_parts[1:]) if len(apellido_parts) > 1 else ''

        # -------------------------------------------------------------
        # 2. Inserción en MySQL (USANDO LA CONTRASEÑA ENCRIPTADA)
        # -------------------------------------------------------------
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
        
        # -------------------------------------------------------------
        # 3. INICIAR TAREA ASÍNCRONA (Subida de documentos y correo)
        # -------------------------------------------------------------
        
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
                apellido_m
            )
        )
        thread.start()

        # Respuesta inmediata al usuario
        return jsonify({'status': 'success', 'message': f'¡{form_data["tipo_personal"].capitalize()} creado. Expediente y correo se están procesando en segundo plano.'}), 202

    except mysql.connector.Error as err:
        if conn: conn.rollback()
        print(f"Error de MySQL: {err}")
        
        error_msg = f'Error en la base de datos: {err}'
        status_code = 500
        
        if err.errno == 1062:
            error_msg = f'Error: El correo electrónico "{email}" ya está registrado.'
            status_code = 400
            
        return jsonify({'status': 'error', 'message': error_msg}), status_code
        
    except Exception as e:
        if conn: conn.rollback()
        print(f"Error general: {e}")
        return jsonify({'status': 'error', 'message': f'Error en el servidor: {e}'}), 500
    finally:
        if 'cursor' in locals() and cursor: cursor.close()
        if conn and conn.is_connected(): conn.close()
        
@app.route("/editar-personal/<string:tipo>/<int:id>", methods=['POST'])
def editar_personal(tipo, id):
    """
    Recibe los datos de edición del personal (maestro o staff) y los actualiza en MySQL.
    """
    conn = None
    
    # Redireccionamos si el método no es POST (aunque la ruta solo acepta POST)
    if request.method != 'POST':
        return redirect(url_for('   ', tipo=tipo, id=id))

    try:
        if tipo not in ['maestro', 'staff']:
            return "Error: Tipo de personal no válido.", 400

        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor()

        # --- 1. ACTUALIZAR DATOS PERSONALES (Maestro o Staff) ---
        
        data = request.form
        
        # Tabla y columna ID
        table_name = "profesores" if tipo == 'maestro' else "staff"
        id_column = "id_profesor" if tipo == 'maestro' else "id_staff"
        
        # Campos de datos personales
        update_fields = [
            'nombre', 'apellido_p', 'apellido_m', 'correo_electronico', 
            'fecha_nacimiento', 'telefono', 'genero'
        ]
        
        # Preparamos la consulta de actualización
        personal_updates = []
        personal_values = []
        
        for field in update_fields:
            # Solo actualizamos campos que tienen un valor en el formulario
            value = data.get(field)
            if value is not None:
                # Evitamos actualizar fechas con cadena vacía si el usuario la borró
                if field == 'fecha_nacimiento' and value == '':
                    personal_updates.append(f"{field} = NULL")
                else:
                    personal_updates.append(f"{field} = %s")
                    personal_values.append(value)
        
        # Si no hay campos que actualizar, nos saltamos la consulta
        if personal_updates:
            query_personal = f"""
                UPDATE {table_name} SET {', '.join(personal_updates)}
                WHERE {id_column} = %s
            """
            personal_values.append(id)
            cursor.execute(query_personal, personal_values)
            
        # --- 2. ACTUALIZAR DATOS FISCALES (SOLO MAESTRO) ---
        if tipo == 'maestro':
            fiscal_fields = ['rfc', 'razon_social', 'regimen_fiscal', 'cuenta_clabe']
            fiscal_updates = []
            fiscal_values = []
            
            # Verificamos si la fila existe en profesores_datos_fiscales antes de actualizar
            cursor.execute("SELECT id_profesor FROM profesores_datos_fiscales WHERE id_profesor = %s", (id,))
            exists = cursor.fetchone()
            
            for field in fiscal_fields:
                value = data.get(field)
                if value is not None:
                    fiscal_updates.append(f"{field} = %s")
                    fiscal_values.append(value)

            if fiscal_updates:
                if exists:
                    # Si existe, actualizamos
                    query_fiscal = f"""
                        UPDATE profesores_datos_fiscales SET {', '.join(fiscal_updates)}
                        WHERE id_profesor = %s
                    """
                    fiscal_values.append(id)
                    cursor.execute(query_fiscal, fiscal_values)
                else:
                    # Si NO existe, insertamos (asumiendo que los campos son obligatorios)
                    fiscal_fields_str = ', '.join(['id_profesor'] + fiscal_fields)
                    placeholders = ', '.join(['%s'] * (len(fiscal_fields) + 1))
                    
                    query_fiscal_insert = f"""
                        INSERT INTO profesores_datos_fiscales ({fiscal_fields_str}) 
                        VALUES ({placeholders})
                    """
                    fiscal_values_insert = [id] + fiscal_values
                    cursor.execute(query_fiscal_insert, fiscal_values_insert)


        conn.commit()
        
    except Exception as e:
        conn.rollback()
        print(f"Error al editar personal: {e}")
        # En un sistema real, aquí mostrarías un mensaje de error al usuario
        return "Error al guardar los cambios: " + str(e), 500
        
    finally:
        if conn and conn.is_connected():
            cursor.close()
            conn.close()

    # Redirecciona a la misma página de detalles para ver los cambios
    return redirect(url_for('maestroinfo', tipo=tipo, id=id))

@app.route('/eliminar-personal/<string:tipo>/<int:id_relacional>', methods=['POST'])
def eliminar_personal(tipo, id_relacional):
    """
    Elimina un registro de personal (profesor o staff) de MySQL y su expediente en MongoDB.
    """
    conn = None
    try:
        # Validación de tipo de personal
        if tipo not in ['maestro', 'staff']:
            return jsonify({'status': 'error', 'message': 'Tipo de personal no válido.'}), 400

        # Determinar nombres de tabla y columna ID
        table_name = "profesores" if tipo == 'maestro' else "staff"
        id_column = "id_profesor" if tipo == 'maestro' else "id_staff"
        
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor()

        # 1. Obtener id_expediente_mongo antes de eliminar el registro principal
        cursor.execute(f"SELECT id_expediente_mongo FROM {table_name} WHERE {id_column} = %s", (id_relacional,))
        mongo_id_tuple = cursor.fetchone()
        mongo_id = mongo_id_tuple[0] if mongo_id_tuple else None

        # 2. Eliminar de MySQL (Asegúrate que se manejen las FK correctamente)
        cursor.execute(f"DELETE FROM {table_name} WHERE {id_column} = %s", (id_relacional,))
        
        if cursor.rowcount == 0:
            conn.rollback()
            return jsonify({'status': 'error', 'message': f'No se encontró {tipo} con ID {id_relacional}.'}), 404

        # 3. Eliminar Expediente de MongoDB
        if mongo_id:
            expedientes_col.delete_one({"_id": ObjectId(mongo_id)})
            
        # 4. Registrar Log (Opcional pero recomendado)
        logs_col.insert_one({
            "tipo_entidad": tipo,
            "id_entidad": id_relacional,
            "accion": "baja_personal",
            "detalle": f"Personal ({tipo}) eliminado del sistema.", 
            "usuario": "admin_logueado", 
            "fecha": datetime.utcnow()
        })
        
        conn.commit()

        return jsonify({'status': 'success', 'message': f'{tipo.capitalize()} eliminado exitosamente.'})

    except Exception as e:
        if conn: conn.rollback()
        # Manejo específico para el error de FK
        if isinstance(e, mysql.connector.Error) and e.errno == 1451:
             error_msg = f"Error: No se puede eliminar al {tipo} ID {id_relacional} porque tiene grupos, comentarios o facturas asignados. Elimine las referencias primero."
             return jsonify({'status': 'error', 'message': error_msg}), 400
        
        print(f"Error al eliminar personal: {e}")
        return jsonify({'status': 'error', 'message': f'Error en el servidor: {e}'}), 500
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
        # La plantilla que acabamos de crear
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

        # 2. Generar un token seguro y establecer la caducidad (ej: 1 hora)
        reset_token = secrets.token_urlsafe(32)
        expiration = datetime.now() + timedelta(hours=1)
        
        # 3. Guardar el token en la base de datos
        query = f"""
            UPDATE {table_name} 
            SET reset_token = %s, token_expiration = %s 
            WHERE correo_electronico = %s
        """
        cursor.execute(query, (reset_token, expiration, email))
        conn.commit()

        # 4. Enviar el correo con el enlace de restablecimiento
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
    """Muestra el formulario de registro de alumnos con catálogos actualizados."""
    conn = None
    try:
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor(dictionary=True)

        # 1. Obtener valores ENUM para campos fijos (genero, tipo_inscripcion)
        cursor.execute("SHOW COLUMNS FROM alumnos LIKE 'genero'")
        genero = parse_enum(cursor.fetchone())

        cursor.execute("SHOW COLUMNS FROM alumnos LIKE 'tipo_inscripcion'")
        tipodeinscripcion = parse_enum(cursor.fetchone())

        # 2. Obtener Catálogo de IDIOMAS (id y nombre)
        cursor.execute("SELECT id_idioma, nombre FROM idioma ORDER BY nombre")
        idiomas = cursor.fetchall()
        
        # 3. Obtener Catálogo de HORARIOS (id y detalle)
        query_horarios = "SELECT id_horario, CONCAT(dias, ' - ', hora, ' (', sede, ')') AS detalle FROM horario ORDER BY dias, hora"
        cursor.execute(query_horarios)
        horarios = cursor.fetchall()

    except mysql.connector.Error as err:
        print("Error:", err)
        genero, tipodeinscripcion, idiomas, horarios = [], [], [], []
    finally:
        if 'conn' in locals() and conn and conn.is_connected():
            cursor.close()
            conn.close()

    return render_template(
        "registro.html",
        genero=genero,
        tipodeinscripcion=tipodeinscripcion,
        idiomas=idiomas,      # Lista de idiomas disponibles
        horarios=horarios      # Lista de horarios disponibles
    )

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
        
        # 1. Capturar las listas de Idiomas y Horarios
        idiomas_seleccionados = request.form.getlist('idiomas[]')
        horarios_seleccionados = request.form.getlist('horarios[]')
        
        # Validar y filtrar pares idioma/horario
        inscripciones_validas = list(zip(idiomas_seleccionados, horarios_seleccionados))
        inscripciones_validas = [(i, h) for i, h in inscripciones_validas if i and h]
        
        if not inscripciones_validas:
             return "<h1>Error: Debe seleccionar al menos un idioma y su horario correspondiente.</h1><a href='/registro'>Volver</a>", 400

        # --- Lógica de Manejo de Archivos (GridFS) ---
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
                # Subir archivo a GridFS
                original_filename_secure = secure_filename(file.filename)
                
                # Guarda el archivo y devuelve su ObjectId
                grid_fs_id = fs.put(
                    file, 
                    filename=original_filename_secure,
                    content_type=file.content_type,
                    alias=mongo_key,
                    usuario_registro=datos["correo"]
                )
                
                # Almacenar el ObjectId de GridFS (como string)
                documentos_mongo[mongo_key] = str(grid_fs_id) 
            else:
                documentos_mongo[mongo_key] = None

        # --- Inserción en MySQL ---
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor()
        
        # Calcular la matrícula
        cursor.execute("SELECT COALESCE(MAX(matricula),16446)+1 FROM alumnos")
        matricula = cursor.fetchone()[0]

        # Inserción en alumnos (sin id_idioma/id_horario)
        cursor.execute("""
            INSERT INTO alumnos 
            (matricula, nombre, apellido_p, apellido_m, correo_electronico, telefono,
             fecha_nacimiento, domicilio, genero, tipo_inscripcion)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """, (
            matricula, datos["nombre"], datos["apellido_p"], datos["apellido_m"], datos["correo"],
            datos["telefono"], datos["fecha_nacimiento"], datos["domicilio"], datos["genero"],
            datos["tipo_inscripcion"]
        ))

        id_alumno = cursor.lastrowid
        
        # Inserción en inscripciones_idioma (Múltiples Registros)
        inscripcion_query = """
            INSERT INTO inscripciones_idioma 
            (id_alumno, id_idioma, id_horario)
            VALUES (%s, %s, %s)
            ON DUPLICATE KEY UPDATE id_alumno = id_alumno;
        """
        for id_idioma, id_horario in inscripciones_validas:
             # Se convierten a int para asegurar el tipo de dato de MySQL
            cursor.execute(inscripcion_query, (id_alumno, int(id_idioma), int(id_horario)))


        # Guardar Expediente en MongoDB (Documentos) y actualizar alumno
        expediente_doc = {
            "tipo": "alumno",
            "id_relacional": id_alumno,
            "documentos": documentos_mongo, # Contiene ObjectIds de GridFS
            "metadata": {
                "fecha_subida": datetime.utcnow(),
                "actualizado_por": "sistema_auto"
            }
        }
        mongo_id = expedientes_col.insert_one(expediente_doc).inserted_id

        cursor.execute(
            "UPDATE alumnos SET id_expediente_mongo = %s WHERE id_alumno = %s",
            (str(mongo_id), id_alumno)
        )

        conn.commit()

        # ... (Resto de la función para logs y retorno) ...
        logs_col.insert_one({
            "tipo_entidad": "alumno",
            "id_entidad": id_alumno,
            "accion": "registro",
            "detalle": "Alumno registrado y expediente creado con documentos en GridFS.",
            "usuario": datos["correo"],
            "fecha": datetime.utcnow()
        })

        return render_template("registro_exitoso.html", matricula=matricula)

    except mysql.connector.Error as err:
        mensaje = f"Error de Base de Datos: {err.msg}"
        print(f"Error de MySQL: {err}")
        if conn and conn.is_connected():
              conn.rollback() 
        return f"<h1>Error en el registro: {mensaje}</h1><a href='/registro'>Volver</a>", 500
        
    except Exception as e:
        mensaje = f"Error General: {e}"
        print(f"Error general en guardar: {e}")
        if conn and conn.is_connected():
              conn.rollback() 
        return f"<h1>Error en el registro: {mensaje}</h1><a href='/registro'>Volver</a>", 500

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

        # Definimos la estrategia de búsqueda: Tabla, Columna ID, Columna Password, Rol
        # El orden importa: Primero busca en Staff, luego Maestros, al final Alumnos
        busqueda_usuarios = [
            {"tabla": "staff",      "id_col": "id_staff",    "rol": "staff"},
            {"tabla": "profesores", "id_col": "id_profesor", "rol": "maestro"},
            {"tabla": "alumnos",    "id_col": "id_alumno",   "rol": "alumno"}
        ]

        usuario_encontrado = None
        datos_usuario = None

        # Bucle para buscar en las 3 tablas
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
            
            print(f"✅ Login exitoso: {session['nombre']} ({session['rol']})")
            
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

@app.route("/asistencias_estudiantes")
def listas():
    return render_template("asistenciasestudiantes.html")

@app.route("/avisos") #maetsro
def avisos():

    avisos_ordenados = sorted(global_avisos, key=lambda x: x['id'], reverse=True)
    return render_template("avisos.html", avisos_publicados=avisos_ordenados)

@app.route("/calificacion") #maetsro
def calificacion():
    return render_template("calificacion.html")

@app.route("/calificaciones") #alumno
def calificaciones():
    return render_template("calificacionesestudiantes.html")

@app.route('/tablero') #alumno
def tablero():
    # Formatear avisos para FullCalendar
    calendar_events = []
    for aviso in global_avisos:
        if 'start' in aviso: # Solo los que tienen fecha_evento
            calendar_events.append({
                'title': aviso['title'],
                'start': aviso['start'],
                'display': 'dot', # ← Esto crea el PUNTO
                'backgroundColor': '#566a93',
                'borderColor': '#566a93'
            })
    
    avisos_ordenados = sorted(global_avisos, key=lambda x: x['id'], reverse=True)
    
    return render_template(
        'tableroestudiantes.html',
        avisos_publicados=avisos_ordenados,
        calendar_events=calendar_events
    )

@app.route('/publicar_aviso', methods=['POST']) #maestros
def publicar_aviso():
    # Nota: Esta función usa una lista global simple. Se recomienda usar la tabla `avisos` de MySQL.
    if request.method == 'POST':
        mensaje_recibido = request.form['mensaje']
        fecha_iso_cal = request.form['fecha_evento']
        now = datetime.now()
        fecha_display = now.strftime("%d/%m/%Y a las %H:%M") 

        # 4. Crear un ID único (simple)
        aviso_id = len(global_avisos) + 1
        
        # 5. Crear el diccionario del aviso (con ambos formatos)
        nuevo_aviso = {
            "id": aviso_id,
            
            # Campos para la lista de avisos
            "fecha": fecha_display,
            "mensaje": mensaje_recibido,
            
            # --- CAMPOS PARA FULLCALENDAR ---
            "title": mensaje_recibido, # El 'título' del evento es el mensaje
            "start": fecha_iso_cal      # La 'fecha' del evento es hoy
        }
        
        # 6. Guardar el aviso en nuestra "base de datos"
        global_avisos.append(nuevo_aviso)
        
        # 7. Redirigir al usuario DE VUELTA a la página de avisos
        return redirect(request.referrer or url_for('avisos'))

@app.route("/evidencias") #maetsro
def evidencias():
    return render_template("evidencias.html")

@app.route("/historial") #staff
def historial():
    return render_template("historial.html")

@app.route("/Maestros") #staff
def Maestros():
    return render_template("listadodemaestros.html")

@app.route("/clasesprofe") #porfe y se queda
def clasesprofe():
    return render_template("clasesprofe.html")

# --- RUTA PRINCIPAL DE ASISTENCIA (MODIFICADA) ---
@app.route("/asistencia")
def asistencia():
    conn = None
    try:
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor(dictionary=True)
        # Simulación: Obtener grupos del profesor logueado
        # En un sistema real usarías: WHERE id_profesor = obtener_profesor_id_simulado()
        query_grupos = """
            SELECT g.id_grupo, CONCAT(g.grupo, ' - ', p.nombre) AS nombre_completo
            FROM grupos g
            JOIN profesores p ON g.id_profesor = p.id_profesor
            WHERE g.id_profesor = %s
            ORDER BY g.grupo
        """
        cursor.execute(query_grupos)
        grupos = cursor.fetchall()

    except Exception as e:
        print(f"Error al cargar grupos para asistencia: {e}")
        grupos = []
    finally:
        if conn and conn.is_connected():
            cursor.close()
            conn.close()

    # Pasa los grupos al template de listas.html para el select
    return render_template("listas.html", grupos=grupos)

@app.route("/obtener_alumnos_grupo/<int:id_grupo>")
def obtener_alumnos_grupo(id_grupo):
    """
    Ruta AJAX para obtener la lista de alumnos de un grupo específico 
    y su asistencia más reciente para el mes en curso.
    """
    conn = None
    try:
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor(dictionary=True)

        # 1. Obtener los alumnos del grupo
        query_alumnos = """
            SELECT 
                a.id_alumno, a.matricula, a.nombre, a.apellido_p, a.apellido_m
            FROM alumnos a
            WHERE a.id_grupo = %s
            ORDER BY a.apellido_p, a.nombre
        """
        cursor.execute(query_alumnos, (id_grupo,))
        alumnos = cursor.fetchall()
        
        # 2. Obtener el total de inasistencias (FALTAS) en la historia (columna ABS)
        # NOTA: En tu diseño, la columna ABS es el total de faltas. 
        # La columna 'ABS' en el HTML original es la última.
        query_faltas = """
            SELECT 
                id_alumno, COUNT(id_asistencias) as total_faltas
            FROM asistencias
            WHERE id_alumno IN (SELECT id_alumno FROM alumnos WHERE id_grupo = %s) AND asistencia = 0
            GROUP BY id_alumno
        """
        cursor.execute(query_faltas, (id_grupo,))
        faltas_data = {item['id_alumno']: item['total_faltas'] for item in cursor.fetchall()}

        # 3. Consolidar los datos
        alumnos_list = []
        for alumno in alumnos:
            nombre_completo = f"{alumno['nombre']} {alumno['apellido_p']} {alumno['apellido_m']}"
            alumnos_list.append({
                'id_alumno': alumno['id_alumno'],
                'matricula': alumno['matricula'],
                'nombre_completo': nombre_completo,
                'faltas': faltas_data.get(alumno['id_alumno'], 0)
                # La asistencia por mes (Enero, Febrero...) se simulará en JS,
                # ya que tu esquema de DB registra la asistencia por día, no por mes.
            })

        return jsonify({'status': 'success', 'alumnos': alumnos_list}), 200

    except Exception as e:
        print(f"Error al obtener alumnos y asistencias: {e}")
        return jsonify({'status': 'error', 'message': f'Error en el servidor: {e}'}), 500
    finally:
        if conn and conn.is_connected():
            cursor.close()
            conn.close()

@app.route("/guardar_asistencia", methods=['POST'])
def guardar_asistencia():
    """
    Ruta AJAX para guardar la asistencia de un alumno para HOY.
    """
    conn = None
    try:
        data = request.get_json()
        id_alumno = data.get('id_alumno')
        id_grupo = data.get('id_grupo')
        es_asistencia = data.get('asistencia') # True/False 
        
        if not id_alumno or not id_grupo is None or es_asistencia is None:
            return jsonify({'status': 'error', 'message': 'Faltan datos requeridos (alumno, grupo, asistencia).'}), 400

        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor()

        # 1. Eliminar registro previo de asistencia/falta para HOY (para evitar duplicados)
        query_delete = """
            DELETE FROM asistencias 
            WHERE id_alumno = %s AND id_grupo = %s 
            AND DATE(fecha_registro) = CURDATE()
        """
        cursor.execute(query_delete, (id_alumno, id_grupo))
        conn.commit()
        
        # 2. Insertar el nuevo registro. 
        # (True = 1/Presente, False = 0/Ausente)
        asistencia_valor = 1 if es_asistencia else 0 

        query_insert = """
            INSERT INTO asistencias 
            (asistencia, id_grupo, id_alumno, id_profesor) 
            VALUES (%s, %s, %s, %s)
        """
        cursor.execute(query_insert, (asistencia_valor, id_grupo, id_alumno))
        conn.commit()

        return jsonify({'status': 'success', 'message': 'Asistencia guardada.'}), 200

    except Exception as e:
        if conn: conn.rollback()
        print(f"Error al guardar asistencia: {e}")
        return jsonify({'status': 'error', 'message': f'Error en el servidor: {e}'}), 500
    finally:
        if conn and conn.is_connected():
            cursor.close()
            conn.close()

@app.route("/comentarios", methods=['GET', 'POST'])
def gestionar_comentarios():
    """
    Ruta AJAX para obtener el historial de comentarios de un alumno o guardar uno nuevo.
    """
    conn = None
    try:
        
        if request.method == 'GET':
            id_alumno = request.args.get('id_alumno', type=int)
            if not id_alumno:
                return jsonify({'status': 'error', 'message': 'ID de alumno es requerido.'}), 400

            conn = mysql.connector.connect(**db_config)
            cursor = conn.cursor(dictionary=True)
            
            # Obtener historial de comentarios
            query_historial = """
                SELECT 
                    c.descripcion, c.fecha_registro, p.nombre, p.apellido_p
                FROM comentarios c
                JOIN profesores p ON c.id_profesor = p.id_profesor
                WHERE c.id_alumno = %s
                ORDER BY c.fecha_registro DESC
            """
            cursor.execute(query_historial, (id_alumno,))
            historial = cursor.fetchall()
            
            # Formatear la fecha para el frontend
            for c in historial:
                c['fecha_registro'] = c['fecha_registro'].strftime('%d/%b/%Y %H:%M')
                c['maestro_nombre'] = f"{c.pop('nombre')} {c.pop('apellido_p')}"

            return jsonify({'status': 'success', 'historial': historial}), 200

        elif request.method == 'POST':
            data = request.get_json()
            id_alumno = data.get('id_alumno')
            descripcion = data.get('descripcion')
            
            if not id_alumno or not descripcion:
                return jsonify({'status': 'error', 'message': 'Faltan datos de alumno o descripción.'}), 400
                
            conn = mysql.connector.connect(**db_config)
            cursor = conn.cursor()
            
            # Insertar nuevo comentario
            query_insert = """
                INSERT INTO comentarios 
                (descripcion, id_alumno, id_profesor) 
                VALUES (%s, %s, %s)
            """
            cursor.execute(query_insert, (descripcion, id_alumno))
            conn.commit()

            # Opcional: Registrar Log en MongoDB
            logs_col.insert_one({
                "tipo_entidad": "alumno",
                "id_entidad": id_alumno,
                "accion": "comentario_guardado",
                "detalle": f"Comentario del profesor: {descripcion[:50]}...",
                "usuario": f"profesor_",
                "fecha": datetime.utcnow()
            })
            
            return jsonify({'status': 'success', 'message': 'Comentario guardado con éxito.'}), 201

    except Exception as e:
        if conn: conn.rollback()
        print(f"Error al gestionar comentarios: {e}")
        return jsonify({'status': 'error', 'message': f'Error en el servidor: {e}'}), 500
    finally:
        if conn and conn.is_connected():
            cursor.close()
            conn.close()

# --- FIN NUEVAS RUTAS ---

@app.route("/maestroinfo/<string:tipo>/<int:id>")
def maestroinfo(tipo, id):
    """
    Obtiene los datos detallados de un Profesor o Staff (MySQL) y sus documentos (MongoDB).
    """
    conn = None
    personal_data = None
    expediente_data = {}
    
    try:
        if tipo not in ['maestro', 'staff']:
            return "Error: Tipo de personal no válido.", 400

        table_name = "profesores" if tipo == 'maestro' else "staff"
        id_column = "id_profesor" if tipo == 'maestro' else "id_staff"
        
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor(dictionary=True)

        # 1. Obtener Datos Personales de MySQL
        query = f"SELECT * FROM {table_name} WHERE {id_column} = %s"
        cursor.execute(query, (id,))
        personal_data = cursor.fetchone()

        if not personal_data:
            return "Personal no encontrado.", 404
        
        # 2. Obtener Documentos de MongoDB
        mongo_id = personal_data.get('id_expediente_mongo')
        if mongo_id:
            expediente_doc = expedientes_col.find_one({"_id": ObjectId(mongo_id)})
            if expediente_doc:
                # Prepara URLs para los documentos encontrados
                for key, filepath in expediente_doc.get('documentos', {}).items():
                    # Usamos la clave de Mongo (key) para el tipo_doc en la URL
                    if filepath:
                        expediente_data[key] = url_for(
                            'ver_documento_expediente', 
                            mongo_id=mongo_id, 
                            tipo_doc=key
                        )
                    else:
                        expediente_data[key] = None

        # 3. Formatear la fecha de nacimiento si existe
        if personal_data.get("fecha_nacimiento"):
            personal_data["fecha_nacimiento"] = personal_data["fecha_nacimiento"].strftime("%d/%m/%Y")
            
        # 4. Obtener datos fiscales si es profesor
        datos_fiscales = None
        if tipo == 'maestro':
            query_fiscal = "SELECT * FROM profesores_datos_fiscales WHERE id_profesor = %s"
            cursor.execute(query_fiscal, (id,))
            datos_fiscales = cursor.fetchone()
            
    except Exception as e:
        print(f"Error en maestroinfo: {e}")
        return "Error interno del servidor.", 500
        
    finally:
        if conn and conn.is_connected():
            cursor.close()
            conn.close()

    return render_template(
        "maestroinfo.html",
        personal=personal_data,
        expediente=expediente_data,
        tipo=tipo,
        datos_fiscales=datos_fiscales
    )

@app.route("/nomina") #actualizar maestros
def nomina():
    return render_template("nomina.html")

@app.route("/perfil") #actualizar password
def perfil():
    return render_template("Perfil.html")

@app.route("/Horario")
def Horario():
    return redirect(url_for('gestion_horarios_base'))

def get_horarios_data():
    """Función auxiliar para obtener horarios formateados."""
    conn = None
    horarios_data = []
    unique_sedes = set()
    day_map_frontend = {'Lun': 1, 'Mar': 2, 'Mié': 3, 'Jue': 4, 'Vie': 5, 'Sáb': 6}

    try:
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT id_horario, sede, dias, hora FROM horario")
        
        for row in cursor.fetchall():
            unique_sedes.add(row['sede'])
            try:
                start, end = row['hora'].split(' - ')
            except:
                start, end = "00:00", "00:00"
            
            dias_list = [d.strip() for d in row['dias'].split(',')]
            for dia_str in dias_list:
                if dia_str in day_map_frontend:
                    horarios_data.append({
                        'id': row['id_horario'],
                        'sede': row['sede'],
                        'dias_str': row['dias'],
                        'day': day_map_frontend[dia_str],
                        'time': start.strip(),
                        'end_time': end.strip()
                    })
    except Exception as e: print(e)
    finally: 
        if conn: conn.close()
    return sorted(list(unique_sedes)), horarios_data

@app.route("/gestion_horarios_base")
def gestion_horarios_base():
    """Vista principal unificada para Horarios y Grupos."""
    conn = None
    try:
        # 1. Sedes y Horarios
        sedes, _ = get_horarios_data()
        
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor(dictionary=True)

        # 2. Profesores (Para select de grupos)
        cursor.execute("SELECT id_profesor, CONCAT(nombre, ' ', apellido_p, ' ', apellido_m) AS nombre_completo FROM profesores")
        profesores = cursor.fetchall()

        # 3. Cursos (Para select de grupos)
        cursor.execute("""
            SELECT c.id_curso, i.nombre AS idioma, c.nivel, h.dias, h.hora, h.sede
            FROM cursos c 
            JOIN idioma i ON c.id_idioma = i.id_idioma 
            JOIN horario h ON c.id_horario = h.id_horario
            ORDER BY i.nombre, c.nivel
        """)
        cursos = cursor.fetchall()

        # 4. Grupos Existentes
        cursor.execute("""
            SELECT g.id_grupo, g.grupo AS nombre_grupo, g.numero_salon,
            CONCAT(p.nombre, ' ', p.apellido_p) AS profesor, i.nombre AS idioma, c.nivel, h.dias, h.hora
            FROM grupos g
            LEFT JOIN profesores p ON g.id_profesor = p.id_profesor
            LEFT JOIN cursos c ON g.id_curso = c.id_curso
            LEFT JOIN idioma i ON c.id_idioma = i.id_idioma
            LEFT JOIN horario h ON c.id_horario = h.id_horario
            ORDER BY g.id_grupo DESC
        """)
        grupos = cursor.fetchall()

        return render_template("crearhorario.html", sedes=sedes, profesores=profesores, cursos=cursos, grupos=grupos)
    except Exception as e:
        return f"Error al cargar vista: {e}", 500
    finally:
        if conn: conn.close()

@app.route("/api/horarios_base", methods=["GET"])
def api_horarios_base():
    _, data = get_horarios_data()
    return jsonify(data)

@app.route("/api/horario_detail/<int:id_horario>", methods=["GET"])
def api_horario_detail(id_horario):
    conn = None
    try:
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM horario WHERE id_horario = %s", (id_horario,))
        row = cursor.fetchone()
        if not row: return jsonify({'status': 'error'}), 404
        parts = row['hora'].split(' - ')
        return jsonify({'status': 'success', 'id_horario': row['id_horario'], 'sede': row['sede'], 'dias': row['dias'].split(', '), 'hora_inicio': parts[0].strip(), 'hora_fin': parts[1].strip()})
    finally:
        if conn: conn.close()

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
        id_raw = data.get('id_horario')
        id_horario = int(id_raw) if id_raw else None
        dias_str = ', '.join(data.get('dias', []))
        hora_str = f"{data.get('hora_inicio')} - {data.get('hora_fin')}"
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor()
        cursor.execute("UPDATE horario SET sede=%s, dias=%s, hora=%s WHERE id_horario=%s", (data.get('sede'), dias_str, hora_str, id_horario))
        conn.commit()
        return jsonify({'status': 'success'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500
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
        if e.errno == 1451: return jsonify({'status': 'error', 'message': 'No se puede eliminar: Horario en uso.'}), 400
        return jsonify({'status': 'error', 'message': str(e)}), 500
    finally:
        if conn: conn.close()

# --- RUTAS PARA GRUPOS (NUEVAS) ---

@app.route("/grupos")
def grupos(): return redirect(url_for('gestion_horarios_base'))

@app.route("/guardar_grupo", methods=["POST"])
def guardar_grupo():
    conn = None
    try:
        f = request.form
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor()
        cursor.execute("INSERT INTO grupos (numero_salon, grupo, id_profesor, id_curso) VALUES (%s,%s,%s,%s)", (f['salon'], f['nombre_grupo'], f['id_profesor'], f['id_curso']))
        conn.commit()
        logs_col.insert_one({"tipo_entidad": "grupo", "accion": "creacion_grupo", "detalle": f"Grupo {f['nombre_grupo']} creado", "fecha": datetime.utcnow()})
        return jsonify({'status': 'success', 'message': 'Grupo creado'})
    except Exception as e: return jsonify({'status': 'error', 'message': str(e)}), 500
    finally: 
        if conn: conn.close()

@app.route("/api/grupo_detail/<int:id_grupo>", methods=["GET"])
def api_grupo_detail(id_grupo):
    """API para obtener detalles de un grupo para editar."""
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
    """API para guardar la edición de un grupo."""
    conn = None
    try:
        f = request.form
        id_grupo = f.get('id_grupo')
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE grupos 
            SET numero_salon=%s, grupo=%s, id_profesor=%s, id_curso=%s
            WHERE id_grupo=%s
        """, (f['salon'], f['nombre_grupo'], f['id_profesor'], f['id_curso'], id_grupo))
        conn.commit()
        return jsonify({'status': 'success', 'message': 'Grupo actualizado correctamente'})
    except Exception as e: return jsonify({'status': 'error', 'message': str(e)}), 500
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

@app.route("/gestion_cursos")
def gestion_cursos():
    """
    Ruta para la gestión de Cursos (idioma, nivel, horario_base).
    Obtiene los catálogos de idiomas y horarios para llenar el formulario.
    """
    conn = None
    idiomas = []
    horarios = []
    cursos_list = []
    
    try:
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor(dictionary=True)

        # 1. Obtener valores ENUM para Niveles
        cursor.execute("SHOW COLUMNS FROM cursos LIKE 'nivel'")
        niveles = parse_enum(cursor.fetchone())

        # 2. Obtener Catálogo de IDIOMAS (id y nombre)
        cursor.execute("SELECT id_idioma, nombre FROM idioma ORDER BY nombre")
        idiomas = cursor.fetchall()
        
        # 3. Obtener Catálogo de HORARIOS BASE (id y detalle)
        query_horarios = "SELECT id_horario, CONCAT(dias, ' - ', hora, ' (', sede, ')') AS detalle FROM horario ORDER BY dias, hora"
        cursor.execute(query_horarios)
        horarios = cursor.fetchall()
        
        # 4. Obtener todos los Cursos existentes
        query_cursos = """
            SELECT 
                c.id_curso,
                i.nombre AS idioma_nombre,
                c.nivel,
                h.dias,
                h.hora,
                h.sede,
                c.club
            FROM cursos c
            JOIN idioma i ON c.id_idioma = i.id_idioma
            JOIN horario h ON c.id_horario = h.id_horario
            ORDER BY i.nombre, c.nivel
        """
        cursor.execute(query_cursos)
        cursos_list = cursor.fetchall()

    except mysql.connector.Error as err:
        print(f"Error de MySQL en gestion_cursos: {err}")
        niveles, idiomas, horarios, cursos_list = [], [], [], []
    finally:
        if conn and conn.is_connected():
            cursor.close()
            conn.close()

    return render_template(
        "curso.html",
        niveles=niveles,
        idiomas=idiomas,
        horarios=horarios,
        cursos=cursos_list
    )

@app.route("/guardar_curso", methods=["POST"])
def guardar_curso():
    conn = None
    try:
        id_idioma = request.form.get('id_idioma', type=int)
        id_horario = request.form.get('id_horario', type=int)
        nivel = request.form.get('nivel')
        club = request.form.get('club')

        if not id_idioma or not id_horario or not nivel:
            return jsonify({'status': 'error', 'message': 'Faltan datos esenciales (Idioma, Horario o Nivel).'}), 400

        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor()

        # Inserción en la tabla `cursos`
        query = """
            INSERT INTO cursos (id_idioma, id_horario, nivel, club)
            VALUES (%s, %s, %s, %s)
        """
        cursor.execute(query, (id_idioma, id_horario, nivel, club))
        id_curso = cursor.lastrowid
        
        conn.commit()

        # Registrar Log
        logs_col.insert_one({
            "tipo_entidad": "curso",
            "id_entidad": id_curso,
            "accion": "creacion_curso",
            "detalle": f"Curso creado. ID_Idioma: {id_idioma}, Nivel: {nivel}, ID_Horario: {id_horario}.",
            "usuario": "admin_logueado", 
            "fecha": datetime.utcnow()
        })

        return jsonify({'status': 'success', 'message': f'Curso (ID: {id_curso}) registrado exitosamente.'}), 201

    except mysql.connector.Error as err:
        if conn: conn.rollback()
        print(f"Error de MySQL al guardar curso: {err}")
        # Error 1062 es duplicado. Podría ser una combinación de FKs única si se definiera
        return jsonify({'status': 'error', 'message': f'Error en la base de datos al guardar curso: {err.msg}'}), 500
    except Exception as e:
        if conn: conn.rollback()
        print(f"Error general al guardar curso: {e}")
        return jsonify({'status': 'error', 'message': f'Error interno del servidor: {e}'}), 500
    finally:
        if conn and conn.is_connected():
            cursor.close()
            conn.close()

@app.route("/eliminar_curso/<int:id_curso>", methods=["POST"])
def eliminar_curso(id_curso):
    conn = None
    try:
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor()

        # Eliminación del curso
        query = "DELETE FROM cursos WHERE id_curso = %s"
        cursor.execute(query, (id_curso,))

        if cursor.rowcount == 0:
            conn.rollback()
            return jsonify({'status': 'error', 'message': f'Curso ID {id_curso} no encontrado.'}), 404

        conn.commit()

        # Registrar Log
        logs_col.insert_one({
            "tipo_entidad": "curso",
            "id_entidad": id_curso,
            "accion": "eliminacion_curso",
            "detalle": f"Curso ID {id_curso} eliminado.",
            "usuario": "admin_logueado", 
            "fecha": datetime.utcnow()
        })

        return jsonify({'status': 'success', 'message': f'Curso ID {id_curso} eliminado exitosamente.'}), 200

    except mysql.connector.Error as err:
        if conn: conn.rollback()
        # Manejo de error de clave foránea (el curso tiene grupos asociados)
        if err.errno == 1451:
            return jsonify({'status': 'error', 'message': 'No se puede eliminar el curso, tiene grupos o alumnos asignados.'}), 400
        print(f"Error de MySQL al eliminar curso: {err}")
        return jsonify({'status': 'error', 'message': f'Error en la base de datos: {err.msg}'}), 500
    except Exception as e:
        if conn: conn.rollback()
        print(f"Error general al eliminar curso: {e}")
        return jsonify({'status': 'error', 'message': f'Error interno del servidor: {e}'}), 500
    finally:
        if conn and conn.is_connected():
            cursor.close()
            conn.close()

# --- FIN RUTAS DE GESTIÓN DE CURSOS ---

@app.route("/reinscripciones") #encabezados, inconos staff
def reinscripciones():
    """
    Muestra la lista de alumnos con información académica y de documentos.
    """
    filtro = request.args.get("tipo", None) 
    alumnos = []
    cursos = []
    grupos = []
    profesores = []
    conn = None
    cursor = None

    try:
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor(dictionary=True)

        # 1. Obtener Cursos, Grupos y Profesores
        cursor.execute("""
            SELECT 
                c.id_curso, 
                CONCAT(i.nombre, ' - Nivel ', c.nivel) AS nombre_completo 
            FROM cursos c
            JOIN idioma i ON c.id_idioma = i.id_idioma
            ORDER BY i.nombre, c.nivel
        """)
        cursos = cursor.fetchall()

        query_grupos = """
            SELECT 
                g.id_grupo, 
                g.grupo, 
                CONCAT(p.nombre, ' ', p.apellido_p) AS nombre_profesor, 
                g.id_profesor
            FROM grupos g
            LEFT JOIN profesores p ON g.id_profesor = p.id_profesor
        """
        cursor.execute(query_grupos)
        grupos = cursor.fetchall()
        
        cursor.execute("SELECT id_profesor, CONCAT(nombre, ' ', apellido_p, ' ', apellido_m) AS nombre_completo FROM profesores")
        profesores = cursor.fetchall()

        # 2. Obtener Alumnos con información académica y Horario Inicial
        query_alumnos = """
             SELECT 
                a.*,
                TIMESTAMPDIFF(YEAR, a.fecha_nacimiento, CURDATE()) AS edad,
                g.grupo AS nombre_grupo,
                CONCAT(p.nombre, ' ', p.apellido_p) AS maestro,
                c.nivel AS nivel_curso,
                -- Subconsulta para obtener el primer horario de inscripción:
                (
                    SELECT CONCAT(h.dias, ' | ', h.hora, ' (', h.sede, ')')
                    FROM inscripciones_idioma ia
                    JOIN horario h ON ia.id_horario = h.id_horario
                    WHERE ia.id_alumno = a.id_alumno
                    ORDER BY ia.fecha_inscripcion ASC
                    LIMIT 1
                ) AS horario
             FROM alumnos a
             LEFT JOIN grupos g ON a.id_grupo = g.id_grupo
             LEFT JOIN profesores p ON g.id_profesor = p.id_profesor
             LEFT JOIN cursos c ON a.id_curso = c.id_curso
        """
        where_clause = ""
        if filtro:
            where_clause = " WHERE a.tipo_inscripcion = %s "
            query_alumnos += where_clause
            cursor.execute(query_alumnos, (filtro,))
        else:
            cursor.execute(query_alumnos) 

        alumnos = cursor.fetchall()

        # 3. Adjuntar información de documentos (Mongo)
        document_fields = ["acta_nacimiento", "identificacion", "formato_descuento", "documentos_comprobatorios", "comprobante_pago"] 
        
        for alumno in alumnos:
            alumno["documentos_urls"] = {}
            
            if alumno.get("id_expediente_mongo"):
                try:
                    expediente = expedientes_col.find_one({"_id": ObjectId(alumno["id_expediente_mongo"])})
                    documentos = expediente.get("documentos", {}) if expediente else {}
                    
                    for tipo_doc in document_fields:
                        if documentos.get(tipo_doc):
                            # Crea una URL accesible para el front-end
                            alumno["documentos_urls"][tipo_doc] = url_for(
                                'ver_documento_expediente', 
                                mongo_id=alumno["id_expediente_mongo"], 
                                tipo_doc=tipo_doc
                            )
                        else:
                            alumno["documentos_urls"][tipo_doc] = None
                            
                except Exception as e:
                    print(f"Error en ObjectId/Mongo para alumno {alumno['id_alumno']}: {e}")
            
            if alumno.get("fecha_nacimiento"):
                alumno["fecha_nacimiento"] = alumno["fecha_nacimiento"].strftime("%d/%m/%Y")


    except Exception as e:
        print("Error en reinscripciones:", e)
    finally:
        if conn and conn.is_connected():
            cursor.close()
            conn.close()

    return render_template(
        "reinscripciones.html", 
        alumnos=alumnos, 
        filtro=filtro,
        cursos=cursos,
        grupos=grupos,
        profesores=profesores
    )

@app.route('/asignar_grupo_curso', methods=['POST'])
def asignar_grupo_curso():
    """Ruta AJAX para actualizar el grupo y el curso (nivel) de un alumno."""
    conn = None
    try:
        # Pasa de JSON a Python
        data = request.get_json()
        id_alumno = data.get('id_alumno')
        id_grupo = data.get('id_grupo')
        id_curso = data.get('id_curso') 
        
        if not id_alumno or not id_grupo or not id_curso:
            return jsonify({'status': 'error', 'message': 'Faltan datos de alumno, grupo o curso.'}), 400

        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor()

        query = """
            UPDATE alumnos 
            SET 
                id_grupo = %s, 
                id_curso = %s
            WHERE id_alumno = %s
        """
        cursor.execute(query, (id_grupo, id_curso, id_alumno))
        
        conn.commit()
        
        logs_col.insert_one({
            "tipo_entidad": "alumno",
            "id_entidad": id_alumno,
            "accion": "asignacion_grupo_curso",
            "detalle": f"Asignado al Grupo ID {id_grupo} y Curso ID {id_curso}.",
            "usuario": "admin_logueado", 
            "fecha": datetime.utcnow()
        })

        return jsonify({'status': 'success', 'message': 'Asignación de grupo/nivel actualizada correctamente.'})

    except mysql.connector.Error as err:
        if conn: conn.rollback()
        print(f"Error de MySQL: {err}")
        return jsonify({'status': 'error', 'message': f'Error en la DB: {err}'}), 500
    except Exception as e:
        if conn: conn.rollback()
        print(f"Error general: {e}")
        return jsonify({'status': 'error', 'message': f'Error del servidor: {e}'}), 500
    finally:
        if conn and conn.is_connected():
            cursor.close()
            conn.close()


@app.route("/enviar_cobro_factura", methods=["POST"])
def enviar_cobro_factura():
    """
    Recibe la información de cobro y descuento, genera credenciales de acceso 
    para el alumno, renderiza la factura HTML y envía el correo electrónico.
    """
    conn = None
    temp_file_path = None
    try:
        data = request.get_json()
        id_alumno = data.get('id_alumno')
        total_a_cobrar = float(data.get('total_a_cobrar'))
        descuentos_aplicados = data.get('descuentos_aplicados')
        porcentaje_aplicado = data.get('porcentaje_aplicado')
        
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor(dictionary=True)

        # 1. Obtener datos del alumno
        cursor.execute(
            "SELECT nombre, apellido_p, apellido_m, correo_electronico, telefono, domicilio, contraseña FROM alumnos WHERE id_alumno = %s",
            (id_alumno,)
        )
        alumno_data = cursor.fetchone()

        if not alumno_data:
            return jsonify({'status': 'error', 'message': 'Alumno no encontrado.'}), 404

        nombre_completo = f"{alumno_data['nombre']} {alumno_data['apellido_p']} {alumno_data['apellido_m']}".strip()
        email = alumno_data['correo_electronico']
        
        # 2. GENERACIÓN DE CONTRASEÑA TEMPORAL (Solo si es NULL/no existe)
        password_hash = alumno_data.get('contraseña')
        contrasena_temporal = None
        
        if not password_hash:
            # Crear contraseña temporal
            caracteres = string.ascii_letters + string.digits
            contrasena_temporal = ''.join(secrets.choice(caracteres) for i in range(10))
            password_encriptada = generate_password_hash(contrasena_temporal)
            
            # Actualizar alumno con el nuevo hash
            cursor.execute(
                "UPDATE alumnos SET contraseña = %s WHERE id_alumno = %s",
                (password_encriptada, id_alumno)
            )
            conn.commit()
            
            # Mensaje para el correo incluyendo las nuevas credenciales
            credenciales_msg = f"""
                <p>También hemos generado credenciales de acceso a su portal de alumno:</p>
                <ul>
                    <li>**Usuario (Correo Electrónico):** <b>{email}</b></li>
                    <li>**Contraseña TEMPORAL:** <b>{contrasena_temporal}</b></li>
                </ul>
                <p>Por favor, utilice este enlace para ingresar: <a href="{url_for('login', _external=True)}">Acceder al Portal de Alumnos</a></p>
                <p>Le recomendamos **cambiar su contraseña inmediatamente** después de iniciar sesión.</p>
            """
        else:
            credenciales_msg = f"""
                <p>Puede acceder con sus credenciales ya existentes al Portal de Alumnos para consultar sus documentos:</p>
                <p><a href="{url_for('login', _external=True)}">Acceder al Portal de Alumnos</a></p>
            """

        # 3. Preparar variables para renderizar la Factura HTML
        costo_base = COSTO_REINSCRIPCION_BASE
        descuento_monto = round(costo_base - total_a_cobrar, 2)
        fecha_actual = datetime.now().strftime("%d/%m/%Y")
        
        # Renderizar la factura HTML (aviso_cobro.html)
        html_factura = render_template('aviso_cobro.html',
            nombre_completo=nombre_completo,
            fecha_actual=fecha_actual,
            telefono=alumno_data.get('telefono', 'N/A'),
            domicilio=alumno_data.get('domicilio', 'N/A'),
            costo_base=costo_base,
            descuento_porcentaje=f"{porcentaje_aplicado}% ({descuentos_aplicados})",
            descuento_monto=descuento_monto,
            total_a_pagar=total_a_cobrar,
            email=email
        )
        
        # 4. CREAR ARCHIVO TEMPORAL (.html) PARA ADJUNTARLO
        temp_filename = f"Aviso_Cobro_{id_alumno}_{datetime.now().strftime('%Y%m%d%H%M%S')}.html"
        # Usamos app.root_path para asegurar que la ruta de guardado sea accesible
        temp_file_path = os.path.join(app.root_path, temp_filename)
        
        with open(temp_file_path, "w", encoding="utf-8") as f:
            f.write(html_factura)

        # 5. ENVÍO DE CORREO (Adjunta el HTML de la Factura)
        if yag:
            subject = f"Aviso de Cobro de Reinscripción - Centro de Idiomas UTR"
            
            # Contenido principal del correo (texto simple para la introducción)
            main_body = [
                f"Hola {nombre_completo},",
                f"<p>Adjunto se encuentra el archivo de su Aviso de Cobro para el proceso de inscripción/reinscripción. Puede descargar y guardar este documento para sus registros.</p>",
                credenciales_msg,
                "<p>Atentamente,<br>Control Escolar CIUTR</p>"
            ]
            
            # Envío con el archivo adjunto
            yag.send(
                to=email, 
                subject=subject, 
                contents=main_body,
                attachments=temp_file_path # Adjunta el archivo HTML renderizado
            ) 

            # 6. Registrar Log de acción
            logs_col.insert_one({
                "tipo_entidad": "alumno",
                "id_entidad": id_alumno,
                "accion": "cobro_enviado",
                "detalle": f"Correo de cobro enviado con adjunto HTML. Total: ${total_a_cobrar:,.2f}. Descuentos: {descuentos_aplicados}", 
                "usuario": "admin_logueado", 
                "fecha": datetime.utcnow()
            })

            return jsonify({'status': 'success', 'message': f'Cobro y credenciales enviados exitosamente a {email}.'}), 200
        else:
            return jsonify({'status': 'error', 'message': 'Error: El servicio de envío de correos (yagmail) no está disponible.'}), 500

    except Exception as e:
        if conn: conn.rollback()
        print(f"Error al enviar cobro/factura: {e}")
        return jsonify({'status': 'error', 'message': f'Error en el servidor al procesar el cobro: {e}'}), 500
    finally:
        # 7. ELIMINAR ARCHIVO TEMPORAL
        if temp_file_path and os.path.exists(temp_file_path):
            try:
                os.remove(temp_file_path)
            except Exception as e:
                print(f"Advertencia: No se pudo eliminar el archivo temporal {temp_file_path}. Error: {e}")
        
        if 'cursor' in locals() and cursor: cursor.close()
        if conn and conn.is_connected(): conn.close()

# =================================================================
# === RUTAS DE FACTURACIÓN ===
# =================================================================

@app.route("/nomina/<int:id_profesor>")
def portal_facturacion(id_profesor):
    """Muestra el borrador de la nómina/factura para el profesor."""
    
    conn = None
    try:
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor(dictionary=True)

        # 1. Obtener datos del PROFESOR (Emisor) y sus datos fiscales
        query_profesor = """
            SELECT 
                p.id_profesor, p.nombre, p.apellido_p, p.apellido_m, 
                f.rfc, f.regimen_fiscal, f.cuenta_clabe
            FROM profesores p
            LEFT JOIN profesores_datos_fiscales f ON p.id_profesor = f.id_profesor
            WHERE p.id_profesor = %s
        """
        cursor.execute(query_profesor, (id_profesor,))
        profesor_data = cursor.fetchone()
        
        if not profesor_data or not profesor_data.get('rfc'):
            return render_template("Portal_Error.html", 
                                    message="Datos fiscales incompletos. Por favor, complete su RFC y Régimen Fiscal.",
                                    id_profesor=id_profesor), 400
            
        # 2. Obtener HORAS TRABAJADAS (SIMULACIÓN)
        horas_trabajadas = 27.0
        periodo_pago = "08 al 27 de Septiembre"

        # 3. Calcular montos fiscales
        montos = calcular_impuestos(horas_trabajadas)
        
    except mysql.connector.Error as err:
        print(f"Error de base de datos al cargar datos fiscales: {err}")
        abort(500, description="Error interno al cargar datos.")
    finally:
        if conn and conn.is_connected():
            cursor.close()
            conn.close()

    # 4. Renderizar la plantilla con todos los datos
    return render_template(
        "Portal.html",
        id_profesor=id_profesor,
        profesor=profesor_data,
        receptor=UTR_DATA,
        periodo=periodo_pago,
        montos=montos,
        VALOR_HORA=VALOR_HORA
    )

@app.route("/timbrar_factura", methods=["POST"])
def timbrar_factura():
    """
    Simula la facturación y guarda el registro en la tabla `facturas_emitidas`.
    """
    id_profesor = request.form.get("id_profesor")
    
    conn = None
    try:
        # 1. Validación de entrada y cálculo
        horas = float(request.form.get("horas"))
        periodo_pago = request.form.get("periodo_pago_hidden")
        montos = calcular_impuestos(horas)
        
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor(dictionary=True)

        # 2. Obtener datos del Emisor (Profesor)
        query_profesor = """
            SELECT p.nombre, p.apellido_p, f.rfc
            FROM profesores p
            JOIN profesores_datos_fiscales f ON p.id_profesor = f.id_profesor
            WHERE p.id_profesor = %s
        """
        cursor.execute(query_profesor, (id_profesor,))
        profesor_data = cursor.fetchone()

        if not profesor_data:
            return abort(404, description=f"Datos de profesor ID: {id_profesor} no encontrados para timbrar.")
        
        # 3. --- SIMULACIÓN DE PAC ---
        uuid_cfdi = str(uuid.uuid4()).upper() 
        
        # Generar las URLs que apuntan a nuestro endpoint de simulación
        with app.app_context():
            url_pdf_prueba = url_for('descargar_archivo_prueba', uuid=uuid_cfdi, tipo='pdf', _external=True)
            url_xml_prueba = url_for('descargar_archivo_prueba', uuid=uuid_cfdi, tipo='xml', _external=True)

        
        # 4. Registrar el CFDI timbrado en MySQL
        cursor.execute("""
            INSERT INTO facturas_emitidas 
            (id_profesor, uuid, subtotal, total, periodo_pago, url_pdf, url_xml)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (
            id_profesor, 
            uuid_cfdi, 
            montos['subtotal'], 
            montos['total_neto'], # total
            periodo_pago,
            url_pdf_prueba, 
            url_xml_prueba 
        ))

        conn.commit()

        # 5. Redirección a la página de éxito
        return redirect(url_for('factura_exitosa', uuid=uuid_cfdi))

    except (TypeError, ValueError) as e:
        return abort(400, description=f"Error en datos de entrada: {e}")
    except mysql.connector.Error as err:
        print(f"Error de DB al timbrar/registrar: {err}")
        if 'conn' in locals() and conn.is_connected():
            conn.rollback()
        return abort(500, description="Error de Base de Datos al registrar la factura.")
    except Exception as e:
        print(f"Error en el proceso de timbrado: {e}")
        return abort(500, description=f"Error inesperado en el servidor: {e}")
    finally:
        if 'conn' in locals() and conn.is_connected():
            cursor.close()
            conn.close()


@app.route("/factura/exito/<string:uuid>")
def factura_exitosa(uuid):
    """Muestra la página de éxito después del timbrado."""
    return render_template("factura_exitosa.html", uuid=uuid)


@app.route('/factura/prueba/<string:uuid>/<string:tipo>')
def descargar_archivo_prueba(uuid, tipo):
    """
    Ruta que SIMULA la descarga del XML o PDF que regresaría el PAC.
    """
    if tipo == 'xml':
        # Simula un XML de CFDI con el UUID real
        xml_content = f"""
<cfdi:Comprobante Version="4.0" Fecha="{datetime.now().isoformat()}" TipoDeComprobante="I" Total="{1234.56}" SubTotal="{1000}" Moneda="MXN" Certificado="...PRUEBA...">
    <cfdi:Emisor Rfc="PROFESOR_RFC" Nombre="PROFESOR_NOMBRE" RegimenFiscal="621"/>
    <cfdi:Receptor Rfc="UTR130212KB3" Nombre="UNIVERSIDAD TECNOLOGICA EL RETOÑO" DomicilioFiscalReceptor="20337" RegimenFiscalReceptor="603" UsoCFDI="G03"/>
    <cfdi:Conceptos>
        <cfdi:Concepto ClaveProdServ="86111702" Cantidad="27" ClaveUnidad="E48" Descripcion="Servicios de Nómina de Prueba (Simulado)" ValorUnitario="105.00" Importe="2835.00"/>
    </cfdi:Conceptos>
    <cfdi:Complemento>
        <tfd:TimbreFiscalDigital Version="1.1" UUID="{uuid}" SelloCFD="...PRUEBA..." SelloSAT="...PRUEBA..." NoCertificadoSAT="...PRUEBA..."/>
    </cfdi:Complemento>
</cfdi:Comprobante>
        """
        response = Response(
            response=xml_content,
            status=200,
            mimetype='application/xml'
        )
        response.headers['Content-Disposition'] = f'attachment; filename={uuid}.xml'
        return response
        
    elif tipo == 'pdf':
        pdf_content_placeholder = f"Esto es la simulación de su Factura PDF Timbrada de PRUEBA.\n\nFolio Fiscal (UUID): {uuid}\n\nFecha de Simulación: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}"
        response = Response(
            response=pdf_content_placeholder,
            status=200,
            mimetype='text/plain'
        )
        response.headers['Content-Disposition'] = f'attachment; filename={uuid}_prueba.txt'
        return response
        
    abort(404)
    
@app.route("/Cerrar")
def cerrar():
    return redirect(url_for('inicio')) 

if __name__ == "__main__":
    app.run(debug=True)