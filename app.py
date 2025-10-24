from flask import Flask, render_template, request, send_from_directory, abort, redirect, url_for, Response
import mysql.connector
from pymongo import MongoClient
from bson import ObjectId
from datetime import datetime
import os
import uuid # Necesario para generar UUID de prueba en la simulación de timbrado
# import requests # Descomentar si se usa una API de PAC real
from werkzeug.utils import secure_filename

app = Flask(__name__)

# --- Inyección Global para Jinja2 ---
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
# === CONFIGURACIONES Y FUNCIONES PARA FACTURACIÓN ===
# =================================================================

# Datos del RECEPTOR (UTR) - Codificados ya que son fijos.
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

# SIMULACIÓN DE API KEY (Usada para la estructura del payload)
FACTURAPI_API_KEY_TEST = "sk_test_BwnLZAk37BQGjCqmpQ9wesXGRlnkahOig5PgQBYX" 
# FACTURAPI_URL_BASE = "https://api.facturapi.io/v1/invoices"

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


# =================================================================
# === RUTAS DE DOCUMENTOS Y AUXILIARES ===
# =================================================================

@app.route('/expediente/ver/<string:mongo_id>/<string:tipo_doc>')
def ver_documento_expediente(mongo_id, tipo_doc):
    """Ruta dinámica para servir documentos desde /uploads."""
    try:
        expediente = expedientes_col.find_one({"_id": ObjectId(mongo_id)})
        
        if not expediente:
            abort(404, description="Expediente no encontrado en MongoDB.")

        full_filepath = expediente.get('documentos', {}).get(tipo_doc)
        
        if not full_filepath:
            abort(404, description=f"Documento '{tipo_doc}' no encontrado en el expediente.")

        # Extraer SÓLO el nombre del archivo de la ruta completa
        filename = os.path.basename(full_filepath)
        
        return send_from_directory(
            UPLOAD_FOLDER, 
            filename,
            as_attachment=False
        )

    except Exception as e:
        print(f"Error al servir documento: {e}")
        abort(500, description="Error interno al acceder al documento.")

def parse_enum(row):
    """Función para extraer valores de un ENUM de MySQL."""
    if not row or "Type" not in row:
        return []
    return row["Type"].replace("enum(", "").replace(")", "").replace("'", "").split(",")


# =================================================================
# === RUTAS ACADÉMICAS Y DE REGISTRO ===
# =================================================================

@app.route("/")
def inicio():
    return render_template("index.html")

@app.route("/registro")
def formulario():
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
                
                # --- CORRECCIÓN DE NOMBRE DE ARCHIVO ---
                original_filename_secure = secure_filename(file.filename)
                name, ext = os.path.splitext(original_filename_secure)
                
                # Nombre único con correo, tipo de documento y timestamp
                filename = f"{secure_filename(datos['correo'])}_{field}_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}{ext}"
                # ---------------------------------------

                filepath = os.path.join(UPLOAD_FOLDER, filename)
                file.save(filepath)
                documentos[field] = filepath 
            else:
                documentos[field] = None

        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor()

        cursor.execute("SELECT COALESCE(MAX(matricula),1000)+1 FROM alumnos")
        matricula = cursor.fetchone()[0]

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

# --- Demás rutas existentes ---
@app.route("/login")
def login():
    return render_template("login.html")

@app.route("/listas_asistencias")
def asistencias():
    return render_template("asistenciasestudiantes.html")

@app.route("/reinscripciones")
def reinscripciones():
    filtro = request.args.get("tipo", None) 
    alumnos = []

    try:
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor(dictionary=True)

        query = """
            SELECT 
                a.*,
                TIMESTAMPDIFF(YEAR, a.fecha_nacimiento, CURDATE()) AS edad,
                g.grupo AS nombre_grupo,
                CONCAT(p.nombre, ' ', p.apellido_p) AS maestro
            FROM alumnos a
            LEFT JOIN grupos g ON a.id_grupo = g.id_grupo
            LEFT JOIN profesores p ON g.id_profesor = p.id_profesor
        """

        if filtro:
            query += " WHERE a.tipo_inscripcion = %s" 
            cursor.execute(query, (filtro,))
        else:
            cursor.execute(query) 

        alumnos = cursor.fetchall()

        # Vincular con MongoDB
        for alumno in alumnos:
            if alumno.get("id_expediente_mongo"):
                try:
                    expediente = expedientes_col.find_one({"_id": ObjectId(alumno["id_expediente_mongo"])})
                    alumno["documentos"] = expediente.get("documentos", {}) if expediente else {}
                except Exception as e:
                    print(f"Error en ObjectId para alumno {alumno['id_alumno']}: {e}")
                    alumno["documentos"] = {}
            else:
                alumno["documentos"] = {}

            if alumno.get("fecha_nacimiento"):
                alumno["fecha_nacimiento"] = alumno["fecha_nacimiento"].strftime("%d/%m/%Y")

    except Exception as e:
        print("Error:", e)
    finally:
        if 'conn' in locals() and conn.is_connected():
            cursor.close()
            conn.close()

    return render_template("reinscripciones.html", alumnos=alumnos, filtro=filtro)

# --- (Otras rutas académicas como /avisos, /calificacion, etc.) ---


# =================================================================
# === RUTAS DE FACTURACIÓN ===
# =================================================================

@app.route("/nomina/<int:id_profesor>")
def portal_facturacion(id_profesor):
    """Muestra el borrador de la nómina/factura para el profesor."""
    
    try:
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor(dictionary=True)

        # 1. Obtener datos del PROFESOR (Emisor) y sus datos fiscales
        query_profesor = """
            SELECT 
                p.id_profesor, p.nombre, p.apellido_p, p.apellido_m, 
                f.rfc, f.regimen_fiscal, f.cuenta_clabe
            FROM profesores p
            JOIN profesores_datos_fiscales f ON p.id_profesor = f.id_profesor
            WHERE p.id_profesor = %s
        """
        cursor.execute(query_profesor, (id_profesor,))
        profesor_data = cursor.fetchone()
        
        if not profesor_data:
            abort(404, description=f"Profesor (ID: {id_profesor}) o sus datos fiscales no encontrados.")
            
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
    Ruta para simular la conexión al PAC, registrar el CFDI, y guardar las URLs 
    simuladas de descarga.
    """
    
    id_profesor = request.form.get("id_profesor")
    
    try:
        # 1. Validación de entrada y cálculo
        try:
            horas = float(request.form.get("horas"))
        except (TypeError, ValueError):
            return abort(400, description="Cantidad de horas inválida.")

        periodo_pago = request.form.get("periodo_pago_hidden")
        montos = calcular_impuestos(horas)
        
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor(dictionary=True)

        # 2. Obtener datos del Emisor (Profesor)
        query_profesor = """
            SELECT p.nombre, p.apellido_p, p.apellido_m, f.rfc, f.regimen_fiscal
            FROM profesores p
            JOIN profesores_datos_fiscales f ON p.id_profesor = f.id_profesor
            WHERE p.id_profesor = %s
        """
        cursor.execute(query_profesor, (id_profesor,))
        profesor_data = cursor.fetchone()

        if not profesor_data:
            return abort(404, description=f"Datos de profesor ID: {id_profesor} no encontrados para timbrar.")
        
        # 3. --- SIMULACIÓN DE ÉXITO Y RECEPCIÓN DE ARCHIVOS ---
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
            montos['total_neto'],
            periodo_pago,
            url_pdf_prueba, # URL de prueba
            url_xml_prueba  # URL de prueba
        ))

        conn.commit()

        # 5. Redirección a la página de éxito
        return redirect(url_for('factura_exitosa', uuid=uuid_cfdi))

    except mysql.connector.Error as err:
        print(f"Error de DB al timbrar/registrar: {err}")
        if 'conn' in locals() and conn.is_connected():
            conn.rollback()
        return abort(500, description="Error de Base de Datos al registrar la factura.")
    except Exception as e:
        print(f"Error en el proceso de timbrado: {e}")
        return abort(500, description=f"Error al conectar con el servicio de timbrado (PAC).")
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
    <cfdi:Emisor Rfc="LAHA000914PZ8" Nombre="ADHARA BELEN LARA HERNANDEZ" RegimenFiscal="621"/>
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
        # Simula un PDF vacío o simple, para demostrar la funcionalidad de descarga.
        pdf_content_placeholder = f"Esto es la simulación de su Factura PDF Timbrada de PRUEBA.\n\nFolio Fiscal (UUID): {uuid}\n\nFecha de Simulación: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}"
        response = Response(
            response=pdf_content_placeholder,
            status=200,
            mimetype='text/plain'
        )
        response.headers['Content-Disposition'] = f'attachment; filename={uuid}_prueba.txt'
        return response
        
    abort(404)


if __name__ == "__main__":
    # Otras rutas sin modificar: /avisos, /calificacion, /clases, /cursos, /evidencias, /grupos, /historial, /Maestros, /listas, /maestroinfo, /nomina (es la nueva), /reinscripciones, /salon, /teachers, /tablero, /Horario, /Cerrar
    app.run(debug=True)