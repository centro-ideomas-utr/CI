from flask import Flask, render_template, request, send_from_directory, abort, redirect, url_for, Response, jsonify
import mysql.connector
from pymongo import MongoClient
from bson import ObjectId
from datetime import datetime
import os
import uuid
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename
import json
from dotenv import load_dotenv
load_dotenv()

app = Flask(__name__)

# Permite usar {{ now.year }} en las plantillas sin pasarlo en cada ruta
@app.context_processor
def inject_now():
    return {'now': datetime.utcnow()}

# --- Configuración de MySQL ---
# ADVERTENCIA: Las credenciales DEBEN ir en variables de entorno en producción.
db_config = {
    "host": "localhost",
    "user": "root",
    "password": "Uli0514122324#",
    "database": "ci_prueba"
}

# --- Configuración de MongoDB ---
MONGO_URI = "mongodb+srv://alucard:Uli0514122324@ci.4v4asta.mongodb.net/?retryWrites=true&w=majority"

mongo_client = MongoClient(MONGO_URI)
mongo_db = mongo_client["ci_prueba"]
expedientes_col = mongo_db["expedientes"]
logs_col = mongo_db["logs"]

# --- Carpeta de uploads ---
UPLOAD_FOLDER = os.path.join(app.root_path, 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)


# =================================================================
# === CONFIGURACIONES Y FUNCIONES AUXILIARES ===
# =================================================================

# Datos del RECEPTOR (UTR) - Fijos para la facturación
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

# =================================================================
# === RUTAS DE DOCUMENTOS Y AUXILIARES ===
# =================================================================

@app.route('/expediente/ver/<string:mongo_id>/<string:tipo_doc>')
def ver_documento_expediente(mongo_id, tipo_doc):
    """
    Ruta dinámica para servir documentos. Consulta Mongo para obtener la ruta del archivo
    y luego sirve el archivo desde el sistema de archivos local (uploads).
    """
    try:
        expediente = expedientes_col.find_one({"_id": ObjectId(mongo_id)})
        
        if not expediente:
            abort(404, description="Expediente no encontrado en MongoDB.")

        # Obtener la ruta COMPLETA del archivo guardada en Mongo
        full_filepath = expediente.get('documentos', {}).get(tipo_doc)
        
        if not full_filepath or not os.path.exists(full_filepath):
            abort(404, description=f"Documento '{tipo_doc}' no encontrado en el servidor.")

        # Extraer SÓLO el nombre del archivo, ya que send_from_directory lo busca en UPLOAD_FOLDER
        filename = os.path.basename(full_filepath) 
        
        return send_from_directory(
            UPLOAD_FOLDER, 
            filename,
            as_attachment=False
        )

    except Exception as e:
        print(f"Error al servir documento: {e}")
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
        # Si la base de datos falla, devolvemos una lista vacía y registramos el error.
        
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
    Guarda los datos personales en MySQL (profesores o staff) y los documentos
    del expediente en el sistema de archivos y MongoDB.
    """
    conn = None
    email = request.form.get('email')
    try:
        nombre = request.form['nombre']
        apellidos = request.form['apellidos'] 
        email = request.form['email']
        telefono = request.form['telefono']
        tipo_personal = request.form['tipo_personal']
        contrasena_plana = request.form['contrasena'] 
        password_encriptada = generate_password_hash(contrasena_plana)
        fecha_nacimiento = request.form.get('fecha_n') 
        genero = request.form.get('genero') 
        
        if fecha_nacimiento == "": fecha_nacimiento = None
        
        # Separar apellidos (asume ApellidoPaterno ApellidoMaterno)
        apellido_parts = apellidos.split(' ')
        apellido_p = apellido_parts[0]
        apellido_m = ' '.join(apellido_parts[1:]) if len(apellido_parts) > 1 else ''

        # Mapeo de campos del formulario a claves de documento en Mongo
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
        
        documentos_mongo = {}
        uploaded_files = request.files

        for form_field, mongo_key in file_mapping.items():
            file = uploaded_files.get(form_field)
            if file and file.filename:
                ext = os.path.splitext(secure_filename(file.filename))[1] or '.pdf'
                # Nombre de archivo único
                filename = f"{secure_filename(email)}_{mongo_key}_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}{ext}"
                filepath = os.path.join(UPLOAD_FOLDER, filename)
                file.save(filepath)
                documentos_mongo[mongo_key] = filepath
            else:
                documentos_mongo[mongo_key] = None

        # -------------------------------------------------------------
        # 2. Inserción en MySQL
        # -------------------------------------------------------------
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor()

        if tipo_personal == 'maestro':
            table_name = "profesores"
            id_column = "id_profesor"
            query = """
                INSERT INTO profesores 
                (nombre, apellido_p, apellido_m, correo_electronico, telefono, fecha_nacimiento, contraseña, genero)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """
            params = (nombre, apellido_p, apellido_m, email, telefono, fecha_nacimiento, password_encriptada, genero)
        
        elif tipo_personal == 'staff':
            table_name = "staff"
            id_column = "id_staff"
            query = """
                INSERT INTO staff 
                (nombre, apellido_p, apellido_m, correo_electronico, telefono, fecha_nacimiento, contraseña)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """
            params = (nombre, apellido_p, apellido_m, email, telefono, fecha_nacimiento, password_encriptada) 
        
        else:
            return jsonify({'status': 'error', 'message': 'Error: Tipo de personal no válido.'}), 400

        cursor.execute(query, params)
        id_personal = cursor.lastrowid
        
        # -------------------------------------------------------------
        # 3. Guardar Expediente en MongoDB
        # -------------------------------------------------------------
        expediente_doc = {
            "tipo": tipo_personal, 
            "id_relacional": id_personal,
            "documentos": documentos_mongo, 
            "metadata": { "fecha_subida": datetime.utcnow(), "actualizado_por": "sistema_admin" }
        }
        mongo_id = expedientes_col.insert_one(expediente_doc).inserted_id
        
        # 4. Actualizar MySQL con el ID de Mongo
        update_query = f"UPDATE {table_name} SET id_expediente_mongo = %s WHERE {id_column} = %s"
        cursor.execute(update_query, (str(mongo_id), id_personal))
        
        conn.commit()

        # 5. Guardar Log
        logs_col.insert_one({
            "tipo_entidad": tipo_personal,
            "id_entidad": id_personal,
            "accion": "registro_personal",
            "detalle": f"Personal ({tipo_personal}) registrado y expediente creado.", 
            "usuario": email, 
            "fecha": datetime.utcnow()
        })
        
        return jsonify({'status': 'success', 'message': f'¡{tipo_personal.capitalize()} guardado exitosamente!'}), 200

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
        if cursor: cursor.close()
        if conn and conn.is_connected(): conn.close()

@app.route("/editar-personal/<string:tipo>/<int:id>", methods=['POST'])
def editar_personal(tipo, id):
    """
    Recibe los datos de edición del personal (maestro o staff) y los actualiza en MySQL.
    """
    conn = None
    
    # Redireccionamos si el método no es POST (aunque la ruta solo acepta POST)
    if request.method != 'POST':
        return redirect(url_for('maestroinfo', tipo=tipo, id=id))

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
# === RUTAS ACADÉMICAS Y DE ALUMNOS ===
# =================================================================

@app.route("/")
def inicio():
    return render_template("index.html")

@app.route("/registro")
def registro():
    """Muestra el formulario de registro de alumnos con opciones ENUM."""
    try:
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor(dictionary=True)

        cursor.execute("SHOW COLUMNS FROM alumnos LIKE 'genero'")
        genero = parse_enum(cursor.fetchone())

        cursor.execute("SHOW COLUMNS FROM alumnos LIKE 'tipo_inscripcion'")
        tipodeinscripcion = parse_enum(cursor.fetchone())

        cursor.execute("SHOW COLUMNS FROM alumnos LIKE 'horario'")
        horarios = parse_enum(cursor.fetchone())

    except mysql.connector.Error as err:
        print("Error:", err)
        genero, tipodeinscripcion, horarios = [], [], []
    finally:
        if 'conn' in locals() and conn.is_connected():
            cursor.close()
            conn.close()

    return render_template(
        "registro.html",
        genero=genero,
        tipodeinscripcion=tipodeinscripcion,
        horarios=horarios
    )

@app.route("/guardar", methods=["POST"])
def guardar():
    """Guarda los datos del alumno en MySQL, documentos en /uploads y referencia en Mongo."""
    conn = None
    try:
        datos = {
            "correo": request.form["correo_electronico"],
            "nombre": request.form["nombre"],
            "apellido_p": request.form["apellido_p"],
            "apellido_m": request.form["apellido_m"],
            "telefono": request.form["telefono"],
            "fecha_nacimiento": datetime.strptime(request.form["fecha_n"], "%Y-%m-%d"),
            "domicilio": request.form["domicilio"],
            "genero": request.form["genero"],
            "tipo_inscripcion": request.form["tipodeinscripcion"],
            "horario": request.form["horario"]
        }

        documentos = {}
        for field in ["acta_n", "identificacion", "comprobante_pago"]:
            file = request.files.get(field) 
            if file and file.filename:
                original_filename_secure = secure_filename(file.filename)
                name, ext = os.path.splitext(original_filename_secure)
                
                # Nombre único con correo, tipo de documento y timestamp
                filename = f"{secure_filename(datos['correo'])}_{field}_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}{ext}"
                filepath = os.path.join(UPLOAD_FOLDER, filename)
                file.save(filepath)
                documentos[field] = filepath 
            else:
                documentos[field] = None

        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor()

        cursor.execute("SELECT COALESCE(MAX(matricula),1000)+1 FROM alumnos")
        matricula = cursor.fetchone()[0]

        # La contraseña se deja vacía o con un valor por defecto si no se requiere login de alumno
        # Si se requiere login, este formulario debe incluir el campo y generar hash
        cursor.execute("""
            INSERT INTO alumnos 
            (matricula, nombre, apellido_p, apellido_m, correo_electronico, telefono,
             fecha_nacimiento, domicilio, genero, tipo_inscripcion, horario)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """, (
            matricula, datos["nombre"], datos["apellido_p"], datos["apellido_m"], datos["correo"],
            datos["telefono"], datos["fecha_nacimiento"], datos["domicilio"], datos["genero"],
            datos["tipo_inscripcion"], datos["horario"]
        ))

        id_alumno = cursor.lastrowid

        # Guardar Expediente en MongoDB
        expediente_doc = {
            "tipo": "alumno",
            "id_relacional": id_alumno,
            "documentos": documentos,
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

        # Guardar Log
        logs_col.insert_one({
            "tipo_entidad": "alumno",
            "id_entidad": id_alumno,
            "accion": "registro",
            "detalle": "Alumno registrado y expediente creado.",
            "usuario": datos["correo"],
            "fecha": datetime.utcnow()
        })

        mensaje = f"Registro exitoso. Matrícula: {matricula}"

    except Exception as e:
        mensaje = f"Error: {e}"
        print(e)
        if 'conn' in locals() and conn.is_connected():
            conn.rollback() 
    finally:
        if 'conn' in locals() and conn.is_connected():
            cursor.close()
            conn.close()

    return f"<h1>{mensaje}</h1><a href='/'>Volver</a>"

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        return render_template("login.html")

    correo = request.form.get("correo_electronico")
    contrasena = request.form.get("contraseña")

    conn = None
    cursor = None

    try:
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor(dictionary=True)

        # Tablas a consultar (prioridad: Staff > Maestro > Alumno)
        user_types = [
            ("staff", "id_staff", "contraseña", "staff"),
            ("profesores", "id_profesor", "contraseña", "maestro"),
            ("alumnos", "id_alumno", "contraseña", "alumno"), # Alumnos con contraseña NULL/plana es un riesgo
        ]
        
        usuario = None
        for table, id_col, pass_col, tipo in user_types:
            cursor.execute(f"""
                SELECT {id_col} AS id, correo_electronico, {pass_col}, '{tipo}' AS tipo
                FROM {table} WHERE correo_electronico = %s
            """, (correo,))
            usuario = cursor.fetchone()
            if usuario:
                break
        
        if not usuario:
            return render_template("login.html", error="Usuario no encontrado.")

        # Verificar contraseña (solo para Staff y Maestros que tienen hash)
        if usuario.get('contraseña') and not check_password_hash(usuario["contraseña"], contrasena):
             return render_template("login.html", error="Contraseña incorrecta.")
        
        # Redirigir según el tipo de usuario
        if usuario["tipo"] == "maestro":
            return redirect(url_for("portal_facturacion", id_profesor=usuario["id"]))
        elif usuario["tipo"] == "alumno":
            return redirect(url_for("tablero"))
        elif usuario["tipo"] == "staff":
            # Redirige a la gestión de personal/reinscripciones
            return redirect(url_for("gestion_personal")) 

        return render_template("login.html", error="Tipo de usuario no válido.")

    except Exception as e:
        print("Error en login:", e)
        return render_template("login.html", error="Error interno del servidor.")
    finally:
        if conn and conn.is_connected():
            cursor.close()
            conn.close()

# --- Demás rutas académicas y de navegación ---

@app.route("/asistencias_estudiantes")
def listas():
    return render_template("asistenciasestudiantes.html")

@app.route("/avisos")
def avisos():
    return render_template("avisos.html")

@app.route("/calificacion")
def calificacion():
    return render_template("calificacion.html")

@app.route("/calificaciones")
def calificaciones():
    return render_template("calificacionesestudiantes.html")

@app.route("/tablero")
def tablero():
    return render_template("tableroestudiantes.html")

@app.route("/clases")
def clases():
    return render_template("listagrupos.html")

@app.route("/cursos")
def cursos():
    return render_template("cursos.html")

@app.route("/evidencias")
def evidencias():
    return render_template("evidencias.html")

@app.route("/grupos")
def grupos():
    return render_template("grupos.html")

@app.route("/historial")
def historial():
    return render_template("historial.html")

@app.route("/Maestros")
def Maestros():
    return render_template("listadodemaestros.html")

@app.route("/clasesprofe")
def clasesprofe():
    return render_template("clasesprofe.html")

@app.route("/asistencia")
def asistencia():
    return render_template("listas.html")

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

@app.route("/nomina")
def nomina():
    return render_template("nomina.html")

@app.route("/Horario")
def Horario():
    return render_template("registromaestro.html")

@app.route("/reinscripciones")
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
        cursor.execute("SELECT id_curso, CONCAT(idioma, ' - Nivel ', nivel) AS nombre_completo FROM cursos")
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

        # 2. Obtener Alumnos (Consulta principal)
        query_alumnos = """
             SELECT 
                a.*,
                TIMESTAMPDIFF(YEAR, a.fecha_nacimiento, CURDATE()) AS edad,
                g.grupo AS nombre_grupo,
                CONCAT(p.nombre, ' ', p.apellido_p) AS maestro,
                c.nivel AS nivel_curso
             FROM alumnos a
             LEFT JOIN grupos g ON a.id_grupo = g.id_grupo
             LEFT JOIN profesores p ON g.id_profesor = p.id_profesor
             LEFT JOIN cursos c ON a.id_curso = c.id_curso
        """
        if filtro:
            query_alumnos += " WHERE a.tipo_inscripcion = %s" 
            cursor.execute(query_alumnos, (filtro,))
        else:
            cursor.execute(query_alumnos) 

        alumnos = cursor.fetchall()

        # 3. Adjuntar información de documentos (Mongo)
        document_fields = ["acta_nacimiento", "identificacion", "comprobante_pago"] # Usar claves de Mongo
        
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
        if 'conn' in locals() and conn.is_connected():
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