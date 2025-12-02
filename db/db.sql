CREATE TABLE alumnos (
    id_alumno INT not null AUTO_INCREMENT PRIMARY KEY,
    matricula INT UNIQUE NOT NULL,
    nombre VARCHAR(100),
    apellido_p VARCHAR(100),
    apellido_m VARCHAR(100),
    correo_electronico VARCHAR(255) UNIQUE NOT NULL,
    telefono VARCHAR(25),
    fecha_nacimiento DATE,
    domicilio VARCHAR(255),
    genero ENUM('M','H'),
    tipo_inscripcion ENUM(
        'REINSCRIPCIÓN ADULTOS REGULARES','REINSCRIPCIÓN ADULTOS DESCUENTO',
        'REINSCRIPCIÓN MENORES REGULAR','REINSCRIPCIÓN MENORES DESCUENTO',
        'INSCRIPCIÓN ADULTOS REGULAR','INSCRIPCIÓN ADULTO DESCUENTO',
        'INSCRIPCIÓN MENORES REGULAR','INSCRIPCIÓN MENORES DESCUENTO'
    ),
    id_expediente_mongo CHAR(24),
    contraseña VARCHAR(255),
	reset_token VARCHAR(100),
	token_expiration DATETIME DEFAULT NULL,
    fecha_registro TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE horario (
    id_horario INT not null AUTO_INCREMENT PRIMARY KEY,
    sede varchar(255),
    dias varchar(255),
    hora varchar(255)
);

CREATE TABLE idioma (
    id_idioma INT not null AUTO_INCREMENT PRIMARY KEY,
	nombre VARCHAR(50) NOT NULL UNIQUE
);

CREATE TABLE cursos (
    id_curso INT not null AUTO_INCREMENT PRIMARY KEY,
    id_idioma INT,
    nivel ENUM('I','II','III','IV','V','VI','VII','VIII','Conv'),
    club varchar(50)
);

CREATE TABLE grupos (
    id_grupo INT not null AUTO_INCREMENT PRIMARY KEY,
    numero_salon VARCHAR (100),
    grupo VARCHAR(100),
    id_profesor INT,
    id_curso INT not null,
    id_horario INT
);

CREATE TABLE profesores (
    id_profesor INT AUTO_INCREMENT PRIMARY KEY,
    nombre VARCHAR(100),
    apellido_p VARCHAR(100),
    apellido_m VARCHAR(100),
    fecha_nacimiento DATE,
    telefono VARCHAR(25),
    correo_electronico VARCHAR(255) UNIQUE NOT NULL,
    contraseña VARCHAR(255),
    id_expediente_mongo CHAR(24),
    genero enum('M','H'),
    reset_token VARCHAR(100),
    token_expiration DATETIME DEFAULT NULL,
    fecha_registro TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    valor_hora float,
    tasa_iva float,
    tasa_isr_retenido float
);

CREATE TABLE staff (
    id_staff INT AUTO_INCREMENT PRIMARY KEY,
    nombre VARCHAR(100),
    apellido_p VARCHAR(100),
    apellido_m VARCHAR(100),
    fecha_nacimiento DATE,
    telefono VARCHAR(25),
    correo_electronico VARCHAR(255) UNIQUE NOT NULL,
    contraseña VARCHAR(255),
    id_expediente_mongo CHAR(24),
    genero enum('M','H'),
    reset_token VARCHAR(100),
	token_expiration DATETIME DEFAULT NULL,
    fecha_registro TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    valor_hora float,
    tasa_iva float,
    tasa_isr_retenido float
);

alter table grupos add constraint foreign key (id_horario) references horario (id_horario);
alter table cursos add constraint foreign key (id_idioma) references idioma (id_idioma);
alter table grupos add constraint foreign key (id_profesor) references profesores(id_profesor);

create table comentarios(
	id_comentario INT not null AUTO_INCREMENT PRIMARY KEY,
	descripcion varchar (255),
	id_alumno int,
	id_profesor int,
	fecha_registro TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

alter table comentarios add constraint foreign key (id_alumno) references alumnos (id_alumno);
alter table comentarios add constraint foreign key (id_profesor) references profesores (id_profesor);

create table asistencias(
	id_asistencias INT not null AUTO_INCREMENT PRIMARY KEY,
    asistencia BOOLEAN,
    inasistencia BOOLEAN,
    id_grupo int,
	id_alumno int,
	id_profesor int,
	fecha_registro TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    fecha_clase DATE NOT NULL,  
);

ALTER TABLE asistencias ADD UNIQUE KEY uk_asistencia_dia (id_alumno, id_grupo, fecha_clase);
alter table asistencias add constraint foreign key (id_grupo) references grupos (id_grupo);
alter table asistencias add constraint foreign key (id_alumno) references alumnos (id_alumno);
alter table asistencias add constraint foreign key (id_profesor) references profesores (id_profesor);

create table calificaciones_adult(
	id_calif_a INT not null AUTO_INCREMENT PRIMARY KEY,
	pronunciation enum('1','2','3','4','5'),
    fluency enum('1','2','3','4','5'),
    grammar_vocabulary enum('1','2','3','4','5'),
    performance_skill enum('1','2','3','4','5'),
    comprenhension enum('1','2','3','4','5'),
    main_ideas enum('1','2','3','4','5'),
    grammar_word_choice enum('1','2','3','4','5'),
    punctuation_capitalization enum('1','2','3','4','5'),
	comentario varchar (500),
    id_grupo int,
	id_alumno int,
	id_profesor int,
	fecha_registro TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

alter table calificaciones_adult add constraint foreign key (id_grupo) references grupos (id_grupo);
alter table calificaciones_adult add constraint foreign key (id_alumno) references alumnos (id_alumno);
alter table calificaciones_adult add constraint foreign key (id_profesor) references profesores (id_profesor);

create table calificaciones_ninos(
	id_calif_k INT not null AUTO_INCREMENT PRIMARY KEY,
	pronunciacion enum('1','2','3'),
    fluidez enum('1','2','3'),
    gramatica_vocabulario enum('1','2','3'),
    habilidades_pronunciacion enum('1','2','3'),
    comprension enum('1','2','3'),
    contenido enum('1','2','3'),
    organizacion enum('1','2','3'),
    lenguaje enum('1','2','3'),
    gramatica enum('1','2','3'),
    ortografia enum('1','2','3'),
    comentario varchar (500),
    id_grupo int,
	id_alumno int,
	id_profesor int,
	fecha_registro TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    parcial ENUM('1','2','3')
);

alter table calificaciones_ninos add constraint foreign key (id_grupo) references grupos (id_grupo);
alter table calificaciones_ninos add constraint foreign key (id_alumno) references alumnos (id_alumno);
alter table calificaciones_ninos add constraint foreign key (id_profesor) references profesores (id_profesor);

create table calificaciones_lsm(
	id_calif_lsm INT not null AUTO_INCREMENT PRIMARY KEY,
	expresiones_faciales enum('1','2','3'),
    movimientos_corporales enum('1','2','3'),
    movimiento_manos enum('1','2','3'),
    identifica_ideograma enum('1','2','3'),
    uos_mano_dominante enum('1','2','3'),
    realiza_dactilogía enum('1','2','3'),
    transmite_mensaje enum('1','2','3'),
    detalles_coordinada enum('1','2','3'),
    orden_secuencial enum('1','2','3'),
    percibir_detalles enum('1','2','3'),
    comprende_mensaje enum('1','2','3'),
    recuerda_senas enum('1','2','3'),
    comentario varchar (500),
    id_grupo int,
	id_alumno int,
	id_profesor int,
	fecha_registro TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    parcial ENUM('1','2','3')
);

alter table calificaciones_lsm add constraint foreign key (id_grupo) references grupos (id_grupo);
alter table calificaciones_lsm add constraint foreign key (id_alumno) references alumnos (id_alumno);
alter table calificaciones_lsm add constraint foreign key (id_profesor) references profesores (id_profesor);

create table calificaciones_prof(
	id_calif_prof INT not null AUTO_INCREMENT PRIMARY KEY,
	conocer enum('1','2','3','4','5'),
    explica enum('1','2','3','4','5'),
    discute enum('1','2','3','4','5'),
    dominio enum('1','2','3','4','5'),
    puntualidad enum('1','2','3','4','5'),
    innovacion enum('1','2','3','4','5'),
    variedad enum('1','2','3','4','5'),
    orden enum('1','2','3','4','5'),
	resolucion enum('1','2','3','4','5'),
    genera enum('1','2','3','4','5'),
    fomento enum('1','2','3','4','5'),
    claridad enum('1','2','3','4','5'),
    instrucciones enum('1','2','3','4','5'),
    recursos enum('1','2','3','4','5'),
    gestion enum('1','2','3','4','5'),
    evalua enum('1','2','3','4','5'),
	evalua_contenidos enum('1','2','3','4','5'),
    informa enum('1','2','3','4','5'),
    brinda enum('1','2','3','4','5'),
    utiliza enum('1','2','3','4','5'),
	proporciona enum('1','2','3','4','5'),
    se_dirige enum('1','2','3','4','5'),
    permite enum('1','2','3','4','5'),
    muestra enum('1','2','3','4','5'),
    comentario varchar (500),
    id_grupo int,
	id_alumno int,
	id_profesor int,
	fecha_registro TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    parcial ENUM('1','2','3')
);

alter table calificaciones_prof add constraint foreign key (id_grupo) references grupos (id_grupo);
alter table calificaciones_prof add constraint foreign key (id_alumno) references alumnos (id_alumno);
alter table calificaciones_prof add constraint foreign key (id_profesor) references profesores (id_profesor);

create table evidencias(
	id_evidencias INT not null AUTO_INCREMENT PRIMARY KEY,
    id_grupo int,
	id_profesor int,
	id_evidencias_mongo CHAR(24),
	fecha_registro TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

alter table evidencias add constraint foreign key (id_grupo) references grupos (id_grupo);
alter table evidencias add constraint foreign key (id_profesor) references profesores (id_profesor);

CREATE TABLE profesores_datos_fiscales (
    id_datos_fiscales INT AUTO_INCREMENT PRIMARY KEY,
    id_profesor INT UNIQUE NOT NULL, 
    rfc VARCHAR(13) UNIQUE NOT NULL,
    razon_social VARCHAR(255) NOT NULL,
    regimen_fiscal VARCHAR(100) NOT NULL, 
    metodo_pago VARCHAR(50), 
    uso_cfdi VARCHAR(50),     
    cuenta_clabe VARCHAR(18),
    codigo_postal varchar(10) DEFAULT NULL
);

alter table profesores_datos_fiscales add constraint foreign key (id_profesor) references profesores (id_profesor);

CREATE TABLE facturas_emitidas (
    id_factura INT AUTO_INCREMENT PRIMARY KEY,
    id_profesor INT NOT NULL,
    uuid CHAR(36) UNIQUE NOT NULL,
    subtotal DECIMAL(10, 2) NOT NULL,
    total DECIMAL(10, 2) NOT NULL,
    periodo_pago VARCHAR(100),
    url_pdf VARCHAR(255),
    url_xml VARCHAR(255),
    fecha_timbrado TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

alter table facturas_emitidas add constraint foreign key (id_profesor) references profesores (id_profesor);

create table avisos(
	id_aviso int not null auto_increment primary key,
    descripcion varchar(500),
    fecha_calendario DATE,
    id_profesor int,
    id_staff int,
    id_grupo INT,
    fecha_registro TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

alter table avisos add constraint foreign key (id_profesor) references profesores (id_profesor);
alter table avisos add constraint foreign key (id_staff) references staff (id_staff);

CREATE TABLE permisos_temporales (
    id_permisos_temporales INT AUTO_INCREMENT PRIMARY KEY,
    id_grupo INT,
    id_profesor INT, 
    id_profesor_sustituto INT, 
    fecha_inicio DATETIME,
    fecha_fin DATETIME,
    estado ENUM('activo', 'expirado', 'revocado') DEFAULT 'activo',
    fecha_creacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

alter table permisos_temporales add constraint foreign key (id_profesor) references profesores (id_profesor);
alter table permisos_temporales add constraint foreign key (id_profesor_sustituto) references profesores (id_profesor);
alter table permisos_temporales add constraint foreign key (id_grupo) references grupos (id_grupo);

CREATE TABLE inscripciones_idioma (
    id_inscripcion INT not null AUTO_INCREMENT PRIMARY KEY,
    id_alumno INT NOT NULL,
    id_idioma INT NOT NULL,
    id_horario INT NOT NULL,
    fecha_inscripcion TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    cobro_enviado BOOLEAN DEFAULT 0,
    id_grupo INT,
    id_curso INT,
    estado ENUM('Activo','Baja temporal','Baja') DEFAULT 'Activo',
    calificacion_final DECIMAL(4,2),
    UNIQUE KEY uk_alumno_idioma_horario (id_alumno, id_idioma, id_horario)
);

alter table inscripciones_idioma ADD CONSTRAINT fk_insc_grupo FOREIGN KEY (id_grupo) REFERENCES grupos(id_grupo),
alter table inscripciones_idioma ADD CONSTRAINT fk_insc_curso FOREIGN KEY (id_curso) REFERENCES cursos(id_curso);
alter table inscripciones_idioma add constraint foreign key (id_alumno) references alumnos (id_alumno);
alter table inscripciones_idioma add constraint foreign key (id_idioma) references idioma (id_idioma);
alter table inscripciones_idioma add constraint foreign key (id_horario) references horario (id_horario);

UPDATE inscripciones_idioma ii
JOIN alumnos a ON ii.id_alumno = a.id_alumno
SET 
    ii.id_grupo = a.id_grupo,
    ii.id_curso = a.id_curso,
    ii.estado = a.estado
WHERE a.id_grupo IS NOT NULL;

create table utr_data(
    id_utr_data int not null auto_increment primary key,
    rfc varchar(14),
    razon_social varchar(50),
    cp int,
    regimen_fiscal varchar(255),
    uso_cfdi varchar(255),
    metodo_pago varchar(255),
    forma_pago varchar(255)
);