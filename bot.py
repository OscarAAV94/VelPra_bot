import logging
import sqlite3
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    ConversationHandler, MessageHandler, filters, ContextTypes
)

# Configuración de logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Estados de conversación ---
(
    REGISTRAR_NOMBRE, REGISTRAR_CI,
    ADMIN_REG_FECHA, ADMIN_REG_ALQUILER, ADMIN_REG_TIPO_ALQ, ADMIN_REG_NUM_PERSONAS,
    ADMIN_REG_INQ_MEDIDOR_LUZ, ADMIN_REG_INQ_MEDIDOR_AGUA, ADMIN_REG_INQ_MEDIDOR_GAS,
    INQ_AMORTIZAR_MONTO, INQ_AMORTIZAR_COMPROBANTE,
    INQ_ENVIAR_QUEJA,
    ADMIN_REG_FACTURA_PROPIEDAD, ADMIN_REG_FACTURA_SERVICIO_TIPO, ADMIN_REG_FACTURA_MONTO,
    ADMIN_REG_LECTURA_PROPIEDAD, ADMIN_REG_LECTURA_MEDIDOR_SELECT, ADMIN_REG_LECTURA_VALOR,
    NOMBRE, # Usado para el flujo de 'nuevo_inquilino' del admin
    ADMIN_REG_INQUILINO_SELECT,
    ADMIN_ELIMINAR_INQUILINO_SELECT, ADMIN_ELIMINAR_INQUILINO_CONFIRM,
    ADMIN_PROPIEDADES_MENU,
    ADMIN_ADD_PROPIEDAD_NOMBRE, ADMIN_ADD_PROPIEDAD_DIRECCION, ADMIN_ADD_PROPIEDAD_SSID, ADMIN_ADD_PROPIEDAD_WIFI,
    ADMIN_DEL_PROPIEDAD_SELECT, ADMIN_DEL_PROPIEDAD_CONFIRM,
    ADMIN_REG_INQUILINO_PROPIEDAD, # Asignar propiedad a inquilino
    ADMIN_ADD_MEDIDOR_PROPIEDAD_SELECT, ADMIN_ADD_MEDIDOR_NOMBRE, ADMIN_ADD_MEDIDOR_TIPO,
    ADMIN_SEND_NOTICE_SCOPE, ADMIN_SEND_NOTICE_PROPERTY_SELECT, ADMIN_SEND_NOTICE_INQUILINO_SELECT, ADMIN_SEND_NOTICE_MESSAGE,
    ADMIN_CONFIRM_PAGO_SELECT, ADMIN_CONFIRM_PAGO_CONFIRM,
    ADMIN_MARK_QUEJA_RESOLVED_SELECT, ADMIN_MARK_QUEJA_RESOLVED_CONFIRM,
    ADMIN_MODIFICAR_INQUILINO_SELECT, ADMIN_MODIFICAR_INQUILINO_FIELD, ADMIN_MODIFICAR_INQUILINO_VALUE,
    ADMIN_GENERAR_COBRO_MENSUAL_SCOPE, ADMIN_GENERAR_COBRO_MENSUAL_PROPERTY_SELECT, ADMIN_GENERAR_COBRO_MENSUAL_CONFIRM,
    # Nuevos estados para submenús de administrador
    ADMIN_MENU_INQUILINOS, ADMIN_MENU_FACTURACION, ADMIN_MENU_COMUNICACION,
    ADMIN_REG_FACTURA_KWH,
    ADMIN_MODIFICAR_PROPIEDAD_SELECT, ADMIN_MODIFICAR_PROPIEDAD_FIELD, ADMIN_MODIFICAR_PROPIEDAD_VALUE # Nuevos estados para modificar propiedad
) = range(54) # Actualizado a 54 para incluir los nuevos estados de modificación de propiedad

# --- Variables globales ---
TOKEN = "8143679562:AAGvdVvxIqYJBNf68qIEtSzcX3LOgaVNzk4" # Reemplaza con tu token de bot
ADMIN_IDS = [5239904442] # Reemplaza con los IDs de Telegram de tus administradores

# --- Base de datos ---
conn = sqlite3.connect('inquilinos.db', check_same_thread=False)
cursor = conn.cursor()

def crear_tablas():
    """Crea las tablas necesarias en la base de datos si no existen."""
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS inquilinos (
            chat_id INTEGER PRIMARY KEY,
            nombre TEXT,
            ci TEXT,
            fecha_ingreso TEXT,
            monto_alquiler REAL,
            tipo_alquiler TEXT,
            saldo REAL DEFAULT 0,
            propiedad_id INTEGER,
            medidor_asignado_luz_id INTEGER,
            medidor_asignado_agua_id INTEGER,
            medidor_asignado_gas_id INTEGER,
            num_personas INTEGER DEFAULT 1,
            FOREIGN KEY (propiedad_id) REFERENCES propiedades(id),
            FOREIGN KEY (medidor_asignado_luz_id) REFERENCES medidores(id),
            FOREIGN KEY (medidor_asignado_agua_id) REFERENCES medidores(id),
            FOREIGN KEY (medidor_asignado_gas_id) REFERENCES medidores(id)
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS pagos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER,
            fecha_pago TEXT,
            monto_pagado REAL,
            saldo_restante REAL,
            comprobante TEXT,
            confirmado INTEGER DEFAULT 0
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS quejas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER,
            fecha TEXT,
            texto TEXT,
            resuelto INTEGER DEFAULT 0
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS facturas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tipo_servicio TEXT,
            fecha TEXT,
            monto REAL,
            propiedad_id INTEGER,
            medidor_id INTEGER,
            total_kwh REAL DEFAULT 0, -- Nueva columna para el total de kWh en facturas de luz
            FOREIGN KEY (propiedad_id) REFERENCES propiedades(id),
            FOREIGN KEY (medidor_id) REFERENCES medidores(id)
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS propiedades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT UNIQUE,
            direccion TEXT,
            wifi_ssid TEXT,
            wifi_password TEXT
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS medidores (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            propiedad_id INTEGER,
            nombre_medidor TEXT,
            tipo_servicio TEXT NOT NULL,
            FOREIGN KEY (propiedad_id) REFERENCES propiedades(id),
            UNIQUE (propiedad_id, nombre_medidor)
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS lecturas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            medidor_id INTEGER,
            fecha TEXT,
            lectura REAL,
            FOREIGN KEY (medidor_id) REFERENCES medidores(id)
        )
    ''')
    conn.commit()

crear_tablas()

# Helper function to escape MarkdownV2 special characters
def escape_markdown_v2(text: str) -> str:
    """Escapes special characters for MarkdownV2 parse mode, excluding * and _ for formatting.
    
    The backslash '\' must be escaped first to prevent issues with other escaped characters.
    """
    # Escape backslash first to prevent double-escaping or issues with later escapes
    text = text.replace('\\', '\\\\')

    # List of other special characters that need to be escaped
    # Exclude '*' and '_' if they are intended for formatting (bold/italic)
    # Based on Telegram Bot API documentation for MarkdownV2:
    # `[`, `]`, `(`, `)`, `~`, `` ` ``, `>`, `#`, `+`, `-`, `=`, `|`, `{`, `}`, `.`, `!`
    special_chars_to_escape = '[]()~`>#+-=|{}.!'
    for char in special_chars_to_escape:
        text = text.replace(char, f'\\{char}')
    
    return text

# --- Funciones para interacciones con la DB ---

def agregar_inquilino(chat_id, nombre, ci):
    """Agrega un nuevo inquilino a la base de datos."""
    cursor.execute(
        "INSERT OR IGNORE INTO inquilinos(chat_id, nombre, ci) VALUES (?, ?, ?)",
        (chat_id, nombre, ci)
    )
    conn.commit()
    logger.info(f"Inquilino {nombre} ({chat_id}) agregado/actualizado.")

def actualizar_datos_inquilino(chat_id, **kwargs):
    """Actualiza los datos de un inquilino existente con campos específicos."""
    updates = []
    params = []
    for key, value in kwargs.items():
        if value is not None:
            updates.append(f"{key} = ?")
            params.append(value)

    if updates:
        query = f"UPDATE inquilinos SET {', '.join(updates)} WHERE chat_id = ?"
        params.append(chat_id)
        cursor.execute(query, tuple(params))
        conn.commit()
        logger.info(f"Datos de inquilino {chat_id} actualizados: {kwargs}")

def obtener_inquilino(chat_id):
    """Obtiene los datos de un inquilino por su chat_id."""
    cursor.execute("SELECT * FROM inquilinos WHERE chat_id = ?", (chat_id,))
    return cursor.fetchone()

def obtener_inquilinos_por_propiedad(propiedad_id):
    """Obtiene todos los inquilinos de una propiedad específica."""
    cursor.execute("SELECT chat_id, nombre, num_personas FROM inquilinos WHERE propiedad_id = ?", (propiedad_id,))
    return cursor.fetchall()

def obtener_todos_los_inquilinos():
    """Obtiene todos los inquilinos registrados."""
    cursor.execute("SELECT chat_id, nombre FROM inquilinos")
    return cursor.fetchall()

def eliminar_inquilino_db(chat_id):
    """Elimina un inquilino y sus registros asociados."""
    try:
        cursor.execute("DELETE FROM pagos WHERE chat_id = ?", (chat_id,))
        cursor.execute("DELETE FROM quejas WHERE chat_id = ?", (chat_id,))
        cursor.execute("DELETE FROM inquilinos WHERE chat_id = ?", (chat_id,))
        conn.commit()
        logger.info(f"Inquilino con chat_id {chat_id} y sus registros eliminados.")
        return True
    except Exception as e:
        logger.error(f"Error al eliminar inquilino {chat_id}: {e}")
        return False

def registrar_pago(chat_id, monto_pagado, saldo_restante, comprobante, confirmado=0):
    """Registra un pago y actualiza el saldo del inquilino."""
    fecha_pago = datetime.now().strftime("%Y-%m-%d")
    cursor.execute(
        "INSERT INTO pagos(chat_id, fecha_pago, monto_pagado, saldo_restante, comprobante, confirmado) VALUES (?, ?, ?, ?, ?, ?)",
        (chat_id, fecha_pago, monto_pagado, saldo_restante, comprobante, confirmado)
    )
    conn.commit()
    logger.info(f"Pago de {monto_pagado} registrado para {chat_id}. Saldo pendiente de confirmación.")

def confirmar_pago_db(pago_id, chat_id, monto_pagado, saldo_restante):
    """Confirma un pago y actualiza el saldo del inquilino."""
    cursor.execute("UPDATE pagos SET confirmado = 1 WHERE id = ?", (pago_id,))
    conn.commit()
    cursor.execute("UPDATE inquilinos SET saldo = ? WHERE chat_id = ?", (saldo_restante, chat_id))
    conn.commit()
    logger.info(f"Pago {pago_id} confirmado para {chat_id}. Nuevo saldo: {saldo_restante}")

def obtener_pagos_pendientes():
    """Obtiene los pagos pendientes de confirmación."""
    cursor.execute("SELECT p.id, p.chat_id, i.nombre, p.fecha_pago, p.monto_pagado, p.saldo_restante, p.comprobante FROM pagos p JOIN inquilinos i ON p.chat_id = i.chat_id WHERE p.confirmado = 0")
    return cursor.fetchall()

def registrar_queja(chat_id, texto):
    """Registra una queja o sugerencia."""
    fecha = datetime.now().strftime("%Y-%m-%d %H:%M")
    cursor.execute(
        "INSERT INTO quejas(chat_id, fecha, texto, resuelto) VALUES (?, ?, ?, 0)",
        (chat_id, fecha, texto)
    )
    conn.commit()
    logger.info(f"Queja registrada de {chat_id}: {texto}")

def obtener_quejas_pendientes():
    """Obtiene las quejas pendientes de resolución."""
    cursor.execute("SELECT q.id, q.chat_id, i.nombre, q.fecha, q.texto FROM quejas q JOIN inquilinos i ON q.chat_id = i.chat_id WHERE q.resuelto = 0 ORDER BY q.fecha DESC")
    return cursor.fetchall()

def marcar_queja_resuelto(queja_id):
    """Marca una queja como resuelta."""
    cursor.execute("UPDATE quejas SET resuelto = 1 WHERE id = ?", (queja_id,))
    conn.commit()
    logger.info(f"Queja {queja_id} marcada como resuelta.")

def agregar_propiedad(nombre, direccion, wifi_ssid, wifi_password):
    """Agrega una nueva propiedad a la base de datos."""
    try:
        cursor.execute(
            "INSERT INTO propiedades(nombre, direccion, wifi_ssid, wifi_password) VALUES (?, ?, ?, ?)",
            (nombre, direccion, wifi_ssid, wifi_password)
        )
        conn.commit()
        logger.info(f"Propiedad '{nombre}' agregada.")
        return True
    except sqlite3.IntegrityError:
        logger.warning(f"Intento de agregar propiedad con nombre duplicado: {nombre}")
        return False
    except Exception as e:
        logger.error(f"Error al agregar propiedad '{nombre}': {e}")
        return False

def actualizar_datos_propiedad(propiedad_id, **kwargs):
    """Actualiza los datos de una propiedad existente con campos específicos."""
    updates = []
    params = []
    for key, value in kwargs.items():
        if value is not None:
            updates.append(f"{key} = ?")
            params.append(value)

    if updates:
        query = f"UPDATE propiedades SET {', '.join(updates)} WHERE id = ?"
        params.append(propiedad_id)
        cursor.execute(query, tuple(params))
        conn.commit()
        logger.info(f"Datos de propiedad {propiedad_id} actualizados: {kwargs}")

def obtener_propiedades():
    """Obtiene todas las propiedades."""
    cursor.execute("SELECT id, nombre, direccion, wifi_ssid, wifi_password FROM propiedades")
    return cursor.fetchall()

def obtener_propiedad_por_id(propiedad_id):
    """Obtiene una propiedad por su ID."""
    cursor.execute("SELECT id, nombre, direccion, wifi_ssid, wifi_password FROM propiedades WHERE id = ?", (propiedad_id,))
    return cursor.fetchone()

def eliminar_propiedad_db(propiedad_id):
    """Elimina una propiedad y sus medidores asociados."""
    try:
        # Desvincular inquilinos de esta propiedad
        cursor.execute("UPDATE inquilinos SET propiedad_id = NULL, medidor_asignado_luz_id = NULL, medidor_asignado_agua_id = NULL, medidor_asignado_gas_id = NULL WHERE propiedad_id = ?", (propiedad_id,))
        # Eliminar lecturas de medidores de esta propiedad
        cursor.execute("DELETE FROM lecturas WHERE medidor_id IN (SELECT id FROM medidores WHERE propiedad_id = ?)", (propiedad_id,))
        # Eliminar medidores asociados a la propiedad
        cursor.execute("DELETE FROM medidores WHERE propiedad_id = ?", (propiedad_id,))
        # Eliminar facturas asociadas a la propiedad
        cursor.execute("DELETE FROM facturas WHERE propiedad_id = ?", (propiedad_id,))
        conn.commit()
        logger.info(f"Propiedad con ID {propiedad_id} y sus datos asociados eliminados.")
        return True
    except Exception as e:
        logger.error(f"Error al eliminar propiedad {propiedad_id}: {e}")
        return False

def agregar_medidor(propiedad_id, nombre_medidor, tipo_servicio):
    """Agrega un nuevo medidor a una propiedad."""
    try:
        cursor.execute(
            "INSERT INTO medidores(propiedad_id, nombre_medidor, tipo_servicio) VALUES (?, ?, ?)",
            (propiedad_id, nombre_medidor, tipo_servicio)
        )
        conn.commit()
        logger.info(f"Medidor '{nombre_medidor}' ({tipo_servicio}) agregado a propiedad {propiedad_id}.")
        return True
    except sqlite3.IntegrityError:
        logger.warning(f"Intento de agregar medidor con nombre duplicado en propiedad {propiedad_id}: {nombre_medidor}")
        return False
    except Exception as e:
        logger.error(f"Error al agregar medidor '{nombre_medidor}' a propiedad {propiedad_id}: {e}")
        return False

def obtener_medidores_por_propiedad(propiedad_id, tipo_servicio=None):
    """Obtiene los medidores de una propiedad específica, opcionalmente filtrado por tipo de servicio."""
    if tipo_servicio:
        cursor.execute("SELECT id, nombre_medidor, tipo_servicio FROM medidores WHERE propiedad_id = ? AND tipo_servicio = ?", (propiedad_id, tipo_servicio))
    else:
        cursor.execute("SELECT id, nombre_medidor, tipo_servicio FROM medidores WHERE propiedad_id = ?", (propiedad_id,))
    return cursor.fetchall()

def obtener_medidor_por_id(medidor_id):
    """Obtiene un medidor por su ID."""
    cursor.execute("SELECT id, propiedad_id, nombre_medidor, tipo_servicio FROM medidores WHERE id = ?", (medidor_id,))
    return cursor.fetchone()

def registrar_lectura_db(medidor_id, lectura):
    """Registra una lectura para un medidor específico."""
    fecha = datetime.now().strftime("%Y-%m-%d")
    cursor.execute(
        "INSERT INTO lecturas(medidor_id, fecha, lectura) VALUES (?, ?, ?)",
        (medidor_id, fecha, lectura)
    )
    conn.commit()
    logger.info(f"Lectura {lectura} registrada para medidor {medidor_id} en fecha {fecha}.")

def obtener_ultima_lectura(medidor_id):
    """Obtiene la última lectura registrada para un medidor."""
    cursor.execute("SELECT lectura FROM lecturas WHERE medidor_id = ? ORDER BY fecha DESC LIMIT 1", (medidor_id,))
    result = cursor.fetchone()
    return result[0] if result else 0.0

def obtener_lectura_anterior_mes(medidor_id, year, month):
    """Obtiene la lectura más cercana al inicio del mes anterior para un medidor."""
    # Calcular el mes anterior
    if month == 1:
        prev_month = 12
        prev_year = year - 1
    else:
        prev_month = month - 1
        prev_year = year

    # Obtener la última lectura del mes anterior
    cursor.execute(
        "SELECT lectura FROM lecturas WHERE medidor_id = ? AND strftime('%Y-%m', fecha) = ? ORDER BY fecha DESC LIMIT 1",
        (medidor_id, f"{prev_year:04d}-{prev_month:02d}")
    )
    result = cursor.fetchone()
    return result[0] if result else 0.0 # Retorna 0 si no hay lectura del mes anterior

def registrar_factura_db(tipo_servicio, monto, propiedad_id, medidor_id=None, total_kwh=0):
    """Registra una factura para una propiedad y opcionalmente un medidor."""
    fecha = datetime.now().strftime("%Y-%m-%d")
    cursor.execute(
        "INSERT INTO facturas(tipo_servicio, fecha, monto, propiedad_id, medidor_id, total_kwh) VALUES (?, ?, ?, ?, ?, ?)",
        (tipo_servicio, fecha, monto, propiedad_id, medidor_id, total_kwh)
    )
    conn.commit()
    logger.info(f"Factura de {tipo_servicio} por {monto} registrada para propiedad {propiedad_id}, medidor {medidor_id}, kWh: {total_kwh}.")

def obtener_facturas_por_medidor_y_mes(medidor_id, year, month):
    """Obtiene la suma de las facturas y el total de kWh para un medidor específico en un mes dado."""
    cursor.execute(
        "SELECT SUM(monto), SUM(total_kwh) FROM facturas WHERE medidor_id = ? AND strftime('%Y-%m', fecha) = ?",
        (medidor_id, f"{year:04d}-{month:02d}")
    )
    result = cursor.fetchone()
    return (result[0] if result and result[0] is not None else 0.0,
            result[1] if result and result[1] is not None else 0.0)

# --- Teclados Inline ---

def teclado_inquilino():
    """Retorna el teclado inline para inquilinos."""
    keyboard = [
        [InlineKeyboardButton("Ver saldo y pagos", callback_data='ver_saldo')],
        [InlineKeyboardButton("Amortizar alquiler", callback_data='amortizar')],
        [InlineKeyboardButton("Enviar queja/sugerencia", callback_data='queja')],
        [InlineKeyboardButton("Ver detalles de mi propiedad", callback_data='ver_mi_propiedad')],
    ]
    return InlineKeyboardMarkup(keyboard)

def teclado_admin():
    """Retorna el teclado inline para administradores, con submenús."""
    keyboard = [
        [InlineKeyboardButton("Gestión de Inquilinos", callback_data='admin_menu_inquilinos')],
        [InlineKeyboardButton("Facturación y Medidores", callback_data='admin_menu_facturacion')],
        [InlineKeyboardButton("Comunicación y Pagos", callback_data='admin_menu_comunicacion')],
    ]
    return InlineKeyboardMarkup(keyboard)

def teclado_admin_inquilinos():
    """Retorna el teclado inline para la gestión de inquilinos."""
    keyboard = [
        [InlineKeyboardButton("Completar registro de inquilino", callback_data='admin_reg_inquilino')],
        [InlineKeyboardButton("Modificar datos de inquilino", callback_data='admin_modificar_inquilino')],
        [InlineKeyboardButton("Añadir nuevo inquilino (manual)", callback_data='admin_nuevo_inquilino')],
        [InlineKeyboardButton("Eliminar inquilino", callback_data='admin_eliminar_inquilino')],
        [InlineKeyboardButton("Ver inquilinos morosos", callback_data='admin_morosos')],
        [InlineKeyboardButton("Volver al menú principal", callback_data='menu_admin')],
    ]
    return InlineKeyboardMarkup(keyboard)

def teclado_admin_facturacion():
    """Retorna el teclado inline para la gestión de facturación y lecturas."""
    keyboard = [
        [InlineKeyboardButton("Registrar factura", callback_data='admin_reg_factura')],
        [InlineKeyboardButton("Registrar lectura contador", callback_data='admin_reg_lectura')],
        [InlineKeyboardButton("Gestionar propiedades y medidores", callback_data='admin_gestionar_propiedades')],
        [InlineKeyboardButton("Ver Resumen Contable", callback_data='admin_resumen_contable')],
        [InlineKeyboardButton("Volver al menú principal", callback_data='menu_admin')],
    ]
    return InlineKeyboardMarkup(keyboard)

def teclado_admin_comunicacion():
    """Retorna el teclado inline para la gestión de comunicación y pagos."""
    keyboard = [
        [InlineKeyboardButton("Generar Cobro Mensual", callback_data='admin_generar_cobro_mensual')],
        [InlineKeyboardButton("Confirmar pagos pendientes", callback_data='admin_confirmar_pagos')],
        [InlineKeyboardButton("Leer quejas y sugerencias", callback_data='admin_quejas')],
        [InlineKeyboardButton("Enviar Aviso", callback_data='admin_send_notice')],
        [InlineKeyboardButton("Volver al menú principal", callback_data='menu_admin')],
    ]
    return InlineKeyboardMarkup(keyboard)

def teclado_gestionar_propiedades():
    """Retorna el teclado inline para gestionar propiedades."""
    keyboard = [
        [InlineKeyboardButton("Ver propiedades", callback_data='admin_ver_propiedades')],
        [InlineKeyboardButton("Añadir propiedad", callback_data='admin_add_propiedad')],
        [InlineKeyboardButton("Modificar propiedad", callback_data='admin_modificar_propiedad')], # Nuevo botón
        [InlineKeyboardButton("Eliminar propiedad", callback_data='admin_del_propiedad')],
        [InlineKeyboardButton("Añadir medidor a propiedad", callback_data='admin_add_medidor')],
        [InlineKeyboardButton("Volver a Facturación y Medidores", callback_data='admin_menu_facturacion')],
    ]
    return InlineKeyboardMarkup(keyboard)

def teclado_send_notice_scope():
    """Retorna el teclado para seleccionar el alcance del aviso."""
    keyboard = [
        [InlineKeyboardButton("Todos en una propiedad", callback_data='notice_scope_property')],
        [InlineKeyboardButton("Un inquilino específico", callback_data='notice_scope_single_inquilino')],
        [InlineKeyboardButton("Volver a Comunicación y Pagos", callback_data='admin_menu_comunicacion')],
    ]
    return InlineKeyboardMarkup(keyboard)

def teclado_tipos_servicio_factura():
    """Retorna el teclado para seleccionar el tipo de servicio (luz, agua, gas, internet_tv) para facturas."""
    keyboard = [
        [InlineKeyboardButton("Luz", callback_data='servicio_luz')],
        [InlineKeyboardButton("Agua", callback_data='servicio_agua')],
        [InlineKeyboardButton("Gas", callback_data='servicio_gas')],
        [InlineKeyboardButton("Internet/TV", callback_data='servicio_internet_tv')],
        [InlineKeyboardButton("Volver", callback_data='admin_menu_facturacion')],
    ]
    return InlineKeyboardMarkup(keyboard)

def teclado_modificar_inquilino_campos():
    """Retorna el teclado para seleccionar el campo a modificar de un inquilino."""
    keyboard = [
        [InlineKeyboardButton("Nombre", callback_data='mod_inq_nombre')],
        [InlineKeyboardButton("CI", callback_data='mod_inq_ci')],
        [InlineKeyboardButton("Fecha de Ingreso", callback_data='mod_inq_fecha_ingreso')],
        [InlineKeyboardButton("Monto Alquiler", callback_data='mod_inq_monto_alquiler')],
        [InlineKeyboardButton("Tipo Alquiler", callback_data='mod_inq_tipo_alquiler')],
        [InlineKeyboardButton("Propiedad", callback_data='mod_inq_propiedad_id')],
        [InlineKeyboardButton("Número de Personas", callback_data='mod_inq_num_personas')],
        [InlineKeyboardButton("Medidor Luz", callback_data='mod_inq_medidor_luz_id')],
        [InlineKeyboardButton("Medidor Agua", callback_data='mod_inq_medidor_agua_id')],
        [InlineKeyboardButton("Medidor Gas", callback_data='mod_inq_medidor_gas_id')],
        [InlineKeyboardButton("Volver a Gestión de Inquilinos", callback_data='admin_menu_inquilinos')],
    ]
    return InlineKeyboardMarkup(keyboard)

def teclado_generar_cobro_mensual_scope():
    """Retorna el teclado para seleccionar el alcance del cobro mensual."""
    keyboard = [
        [InlineKeyboardButton("Todos los inquilinos", callback_data='charge_scope_all')],
        [InlineKeyboardButton("Inquilinos de una propiedad", callback_data='charge_scope_property')],
        [InlineKeyboardButton("Volver a Comunicación y Pagos", callback_data='admin_menu_comunicacion')],
    ]
    return InlineKeyboardMarkup(keyboard)


def boton_volver_menu(usuario='inquilino', menu_destino=''):
    """Retorna un botón para volver a un menú específico o al principal del usuario."""
    if menu_destino == 'admin_propiedades':
        return InlineKeyboardMarkup([[InlineKeyboardButton("Volver a Gestión de Propiedades", callback_data='admin_gestionar_propiedades')]])
    elif menu_destino == 'admin_modificar_inquilino':
        return InlineKeyboardMarkup([[InlineKeyboardButton("Volver a Modificar Inquilino", callback_data='admin_modificar_inquilino')]])
    elif menu_destino == 'admin_menu_inquilinos':
        return InlineKeyboardMarkup([[InlineKeyboardButton("Volver a Gestión de Inquilinos", callback_data='admin_menu_inquilinos')]])
    elif menu_destino == 'admin_menu_facturacion':
        return InlineKeyboardMarkup([[InlineKeyboardButton("Volver a Facturación y Medidores", callback_data='admin_menu_facturacion')]])
    elif menu_destino == 'admin_menu_comunicacion':
        return InlineKeyboardMarkup([[InlineKeyboardButton("Volver a Comunicación y Pagos", callback_data='admin_menu_comunicacion')]])
    elif usuario == 'admin':
        return InlineKeyboardMarkup([[InlineKeyboardButton("Volver al menú principal", callback_data='menu_admin')]])
    else: # Default para inquilino
        return InlineKeyboardMarkup([[InlineKeyboardButton("Volver al menú principal", callback_data='menu_inquilino')]])

# --- Handlers principales ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Maneja el comando /start y dirige al usuario al menú apropiado, editando el mensaje si es una callback."""
    chat_id = update.effective_chat.id
    
    message_editor = None
    if update.callback_query:
        await update.callback_query.answer() # Acknowledge the callback immediately
        message_editor = update.callback_query.edit_message_text
    elif update.message:
        message_editor = update.message.reply_text

    if not message_editor:
        logger.error("No se pudo determinar el editor de mensajes en start.")
        return ConversationHandler.END

    if chat_id in ADMIN_IDS:
        await message_editor(
            escape_markdown_v2("Bienvenido al panel administrador."), reply_markup=teclado_admin(), parse_mode='MarkdownV2'
        )
    else:
        inquilino = obtener_inquilino(chat_id)
        if inquilino and inquilino[3] is not None: # Si el inquilino está completamente registrado (tiene fecha de ingreso)
            await message_editor(
                escape_markdown_v2(f"Hola {escape_markdown_v2(inquilino[1])}, bienvenido a tu panel."), reply_markup=teclado_inquilino(), parse_mode='MarkdownV2'
            )
        else: # Nuevo inquilino o registro pendiente/incompleto
            if inquilino: # Inquilino existe pero registro incompleto
                await message_editor(
                    escape_markdown_v2(f"Hola {escape_markdown_v2(inquilino[1])}, tu registro está pendiente de validación por el administrador. "
                    "Usa /start para verificar tu estado."),
                    parse_mode='MarkdownV2'
                )
            else: # Inquilino no registrado
                await message_editor(
                    escape_markdown_v2("¡Bienvenido! Para comenzar, por favor registra tu nombre completo:"), parse_mode='MarkdownV2'
                )
                return REGISTRAR_NOMBRE
    return ConversationHandler.END

async def registrar_nombre(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Pide el nombre completo del inquilino para el registro inicial."""
    nombre = update.message.text.strip()
    if not nombre:
        await update.message.reply_text(escape_markdown_v2("El nombre no puede estar vacío. Por favor, ingresa tu nombre completo:"), parse_mode='MarkdownV2')
        return REGISTRAR_NOMBRE
    context.user_data['nombre'] = nombre
    await update.message.reply_text(escape_markdown_v2("Ahora ingresa tu número de carnet de identidad:"), parse_mode='MarkdownV2')
    return REGISTRAR_CI

async def registrar_ci(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Pide el CI del inquilino y lo registra inicialmente."""
    chat_id = update.effective_chat.id
    ci = update.message.text.strip()
    if not ci:
        await update.message.reply_text(escape_markdown_v2("El CI no puede estar vacío. Por favor, ingresa tu número de carnet de identidad:"), parse_mode='MarkdownV2')
        return REGISTRAR_CI
    nombre = context.user_data.get('nombre')
    agregar_inquilino(chat_id, nombre, ci)
    # No mostrar el teclado del inquilino hasta que el registro sea validado por el admin
    await update.message.reply_text(
        escape_markdown_v2(f"Gracias {escape_markdown_v2(nombre)}, tu registro está pendiente de validación por el administrador. "
        "Usa /start para verificar tu estado."),
        parse_mode='MarkdownV2'
    )
    return ConversationHandler.END

# --- Handlers para iniciar conversaciones desde callbacks (Admin) ---

async def handle_admin_menu_inquilinos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Muestra el menú de gestión de inquilinos."""
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(escape_markdown_v2("Menú de Gestión de Inquilinos:"), reply_markup=teclado_admin_inquilinos(), parse_mode='MarkdownV2')
    return ConversationHandler.END

async def handle_admin_menu_facturacion(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Muestra el menú de facturación y medidores."""
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(escape_markdown_v2("Menú de Facturación y Medidores:"), reply_markup=teclado_admin_facturacion(), parse_mode='MarkdownV2')
    return ConversationHandler.END

async def handle_admin_menu_comunicacion(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Muestra el menú de comunicación y pagos."""
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(escape_markdown_v2("Menú de Comunicación y Pagos:"), reply_markup=teclado_admin_comunicacion(), parse_mode='MarkdownV2')
    return ConversationHandler.END

async def handle_admin_reg_inquilino_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Maneja el click en 'Completar registro de inquilino' y muestra la lista de pendientes."""
    query = update.callback_query
    await query.answer()
    cursor.execute("SELECT chat_id, nombre, ci FROM inquilinos WHERE fecha_ingreso IS NULL")
    pendientes = cursor.fetchall()
    if not pendientes:
        await query.edit_message_text(
            escape_markdown_v2("No hay inquilinos pendientes de completar registro."),
            reply_markup=teclado_admin_inquilinos(), parse_mode='MarkdownV2'
        )
        return ConversationHandler.END
    buttons = [
        [InlineKeyboardButton(escape_markdown_v2(f"{nom} (CI: {ci})"), callback_data=f"reginqui_{cid}")]
        for cid, nom, ci in pendientes
    ]
    buttons.append([InlineKeyboardButton("Volver", callback_data='admin_menu_inquilinos')])
    await query.edit_message_text(
        escape_markdown_v2("Selecciona un inquilino para completar registro:"),
        reply_markup=InlineKeyboardMarkup(buttons), parse_mode='MarkdownV2'
    )
    return ADMIN_REG_INQUILINO_SELECT

async def handle_reginqui_selection_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Maneja la selección de un inquilino pendiente por el admin."""
    query = update.callback_query
    await query.answer()
    cid = int(query.data.split("_")[1])
    context.user_data['reginqui_chatid'] = cid
    await query.edit_message_text(
        escape_markdown_v2("Ingresa la fecha de ingreso (YYYY-MM-DD):"),
        reply_markup=boton_volver_menu('admin', 'admin_menu_inquilinos'), parse_mode='MarkdownV2'
    )
    return ADMIN_REG_FECHA

async def admin_reg_fecha(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Maneja la entrada de la fecha de ingreso para el registro de inquilinos."""
    message_editor = update.message.reply_text if update.message else update.callback_query.edit_message_text
    if update.callback_query: await update.callback_query.answer()

    texto = update.effective_message.text.strip()
    chat_id_reg = context.user_data.get('reginqui_chatid')
    if not chat_id_reg:
        await message_editor(escape_markdown_v2("Error: No se encontró el inquilino. Por favor, vuelve a intentar desde el menú admin."),
                                        reply_markup=teclado_admin(), parse_mode='MarkdownV2')
        return ConversationHandler.END
    try:
        datetime.strptime(texto, '%Y-%m-%d')
    except ValueError:
        await message_editor(escape_markdown_v2("Fecha inválida. Usa formato YYYY-MM-DD. Intenta de nuevo:"), parse_mode='MarkdownV2')
        return ADMIN_REG_FECHA
    actualizar_datos_inquilino(chat_id_reg, fecha_ingreso=texto)
    context.user_data['reg_fecha'] = texto
    await update.message.reply_text( # Usar reply_text aquí porque es una respuesta a un mensaje de texto
        escape_markdown_v2("Fecha guardada. Ahora ingresa el monto del alquiler:"),
        reply_markup=boton_volver_menu('admin', 'admin_menu_inquilinos'), parse_mode='MarkdownV2'
    )
    return ADMIN_REG_ALQUILER

async def admin_reg_monto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Maneja la entrada del monto del alquiler para el registro de inquilinos."""
    message_editor = update.message.reply_text if update.message else update.callback_query.edit_message_text
    if update.callback_query: await update.callback_query.answer()

    texto = update.effective_message.text.strip()
    chat_id_reg = context.user_data.get('reginqui_chatid')
    if not chat_id_reg:
        await message_editor(escape_markdown_v2("Error: No se encontró el inquilino. Por favor, vuelve a intentar desde el menú admin."),
                                        reply_markup=teclado_admin(), parse_mode='MarkdownV2')
        return ConversationHandler.END
    try:
        monto = float(texto)
        if monto <= 0:
            raise ValueError("El monto debe ser positivo.")
    except ValueError:
        await update.message.reply_text(escape_markdown_v2("Monto inválido. Ingresa un número válido y positivo. Intenta de nuevo:"), parse_mode='MarkdownV2')
        return ADMIN_REG_ALQUILER
    actualizar_datos_inquilino(chat_id_reg, monto_alquiler=monto)
    await update.message.reply_text( # Usar reply_text aquí porque es una respuesta a un mensaje de texto
        escape_markdown_v2("Monto guardado. Ahora selecciona el tipo de alquiler:"),
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("Todo incluido", callback_data='tipo_todo')],
            [InlineKeyboardButton("Prorrateo servicios", callback_data='tipo_prorrateo')],
        ]), parse_mode='MarkdownV2'
    )
    return ADMIN_REG_TIPO_ALQ

async def admin_reg_tipo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Maneja la selección del tipo de alquiler y pide la propiedad."""
    query = update.callback_query
    await query.answer()
    chat_id_reg = context.user_data.get('reginqui_chatid')
    if not chat_id_reg:
        await query.edit_message_text(escape_markdown_v2("Error: No se encontró el inquilino. Por favor, vuelve a intentar desde el menú admin."),
                                      reply_markup=teclado_admin(), parse_mode='MarkdownV2')
        return ConversationHandler.END

    tipo = query.data.split("_")[1]
    context.user_data['reginqui_tipo_alquiler'] = tipo
    actualizar_datos_inquilino(chat_id_reg, tipo_alquiler=tipo)

    propiedades = obtener_propiedades()
    if not propiedades:
        await query.edit_message_text(escape_markdown_v2("No hay propiedades registradas. Por favor, registra una propiedad primero."),
                                      reply_markup=teclado_admin_inquilinos(), parse_mode='MarkdownV2')
        return ConversationHandler.END

    buttons = [[InlineKeyboardButton(escape_markdown_v2(p[1]), callback_data=f"propiedad_sel_{p[0]}")] for p in propiedades]
    buttons.append([InlineKeyboardButton("Volver", callback_data='admin_menu_inquilinos')])
    await query.edit_message_text(escape_markdown_v2("Selecciona la propiedad para este inquilino:"),
                                  reply_markup=InlineKeyboardMarkup(buttons), parse_mode='MarkdownV2')
    return ADMIN_REG_INQUILINO_PROPIEDAD

async def admin_reg_inquilino_propiedad(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Maneja la selección de propiedad para el inquilino."""
    query = update.callback_query
    await query.answer()
    propiedad_id = int(query.data.split("_")[2])
    context.user_data['reginqui_propiedad_id'] = propiedad_id
    chat_id_reg = context.user_data.get('reginqui_chatid')
    actualizar_datos_inquilino(chat_id_reg, propiedad_id=propiedad_id)

    await query.edit_message_text(
        escape_markdown_v2("Ingresa el número de personas que vivirán con el inquilino (incluyéndolo a él):"),
        reply_markup=boton_volver_menu('admin', 'admin_menu_inquilinos'), parse_mode='MarkdownV2'
    )
    return ADMIN_REG_NUM_PERSONAS

async def admin_reg_num_personas(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Maneja la entrada del número de personas para el inquilino."""
    message_editor = update.message.reply_text if update.message else update.callback_query.edit_message_text
    if update.callback_query: await update.callback_query.answer()

    texto = update.effective_message.text.strip()
    chat_id_reg = context.user_data.get('reginqui_chatid')
    try:
        num_personas = int(texto)
        if num_personas <= 0:
            raise ValueError("El número de personas debe ser positivo.")
    except ValueError:
        await update.message.reply_text(escape_markdown_v2("Número inválido. Ingresa un número entero positivo. Intenta de nuevo:"), parse_mode='MarkdownV2')
        return ADMIN_REG_NUM_PERSONAS

    actualizar_datos_inquilino(chat_id_reg, num_personas=num_personas)
    context.user_data['reginqui_num_personas'] = num_personas

    tipo_alquiler = context.user_data.get('reginqui_tipo_alquiler')
    propiedad_id = context.user_data.get('reginqui_propiedad_id')

    if tipo_alquiler == 'prorrateo':
        # Usar edit_message_text si la interacción previa fue un callback, sino reply_text
        if update.callback_query:
            return await _ask_for_medidor(update, context, 'luz', editor_func=update.callback_query.edit_message_text)
        else:
            return await _ask_for_medidor(update, context, 'luz', editor_func=update.message.reply_text)
    else: # Todo incluido
        if update.callback_query:
            await update.callback_query.edit_message_text(escape_markdown_v2("Registro completo para el inquilino."), reply_markup=teclado_admin_inquilinos(), parse_mode='MarkdownV2')
        else:
            await update.message.reply_text(escape_markdown_v2("Registro completo para el inquilino."), reply_markup=teclado_admin_inquilinos(), parse_mode='MarkdownV2')
        await send_welcome_and_wifi_key_to_inquilino(context, chat_id_reg, propiedad_id)
        return ConversationHandler.END

async def _ask_for_medidor(update: Update, context: ContextTypes.DEFAULT_TYPE, service_type: str, editor_func):
    """Helper function to ask for medidor for a given service type."""
    chat_id_reg = context.user_data.get('reginqui_chatid')
    propiedad_id = context.user_data.get('reginqui_propiedad_id')

    medidores = obtener_medidores_por_propiedad(propiedad_id, service_type)
    
    current_state = {
        'luz': ADMIN_REG_INQ_MEDIDOR_LUZ,
        'agua': ADMIN_REG_INQ_MEDIDOR_AGUA,
        'gas': ADMIN_REG_INQ_MEDIDOR_GAS
    }
    
    next_service_type = {
        'luz': 'agua',
        'agua': 'gas',
        'gas': None
    }

    if medidores:
        buttons = [[InlineKeyboardButton(escape_markdown_v2(m[1]), callback_data=f"med{service_type}_sel_{m[0]}")] for m in medidores]
        buttons.append([InlineKeyboardButton("Ninguno", callback_data=f"med{service_type}_sel_none")])
        buttons.append([InlineKeyboardButton("Volver", callback_data='admin_menu_inquilinos')]) # Botón de volver
        
        message_text = escape_markdown_v2(f"Selecciona el medidor de *{service_type.upper()}* asignado a este inquilino:")
        
        await editor_func(message_text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode='MarkdownV2')
        
        return current_state[service_type]
    else:
        if service_type == 'luz':
            actualizar_datos_inquilino(chat_id_reg, medidor_asignado_luz_id=None)
        elif service_type == 'agua':
            actualizar_datos_inquilino(chat_id_reg, medidor_asignado_agua_id=None)
        elif service_type == 'gas':
            actualizar_datos_inquilino(chat_id_reg, medidor_asignado_gas_id=None)

        message_text = escape_markdown_v2(f"No hay medidores de *{service_type.upper()}* para esta propiedad. ")
        
        if next_service_type[service_type]:
            message_text += escape_markdown_v2(f"Continuar con *{next_service_type[service_type].capitalize()}*.")
            await editor_func(message_text, parse_mode='MarkdownV2')
            return await _ask_for_medidor(update, context, next_service_type[service_type], editor_func)
        else:
            message_text += escape_markdown_v2("Registro completo.")
            await editor_func(message_text, reply_markup=teclado_admin_inquilinos(), parse_mode='MarkdownV2')
            await send_welcome_and_wifi_key_to_inquilino(context, chat_id_reg, propiedad_id)
            return ConversationHandler.END


async def admin_reg_inq_medidor_luz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Maneja la selección del medidor de luz para el inquilino."""
    query = update.callback_query
    await query.answer()

    chat_id_reg = context.user_data.get('reginqui_chatid')
    medidor_luz_id = int(query.data.split("_")[2]) if query.data != 'medluz_sel_none' else None
    actualizar_datos_inquilino(chat_id_reg, medidor_asignado_luz_id=medidor_luz_id)
    
    return await _ask_for_medidor(update, context, 'agua', editor_func=query.edit_message_text)

async def admin_reg_inq_medidor_agua(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Maneja la selección del medidor de agua para el inquilino."""
    query = update.callback_query
    await query.answer()

    chat_id_reg = context.user_data.get('reginqui_chatid')
    medidor_agua_id = int(query.data.split("_")[2]) if query.data != 'medagua_sel_none' else None
    actualizar_datos_inquilino(chat_id_reg, medidor_asignado_agua_id=medidor_agua_id)

    return await _ask_for_medidor(update, context, 'gas', editor_func=query.edit_message_text)

async def admin_reg_inq_medidor_gas(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Maneja la selección del medidor de gas para el inquilino y finaliza el registro."""
    query = update.callback_query
    await query.answer()

    chat_id_reg = context.user_data.get('reginqui_chatid')
    propiedad_id = context.user_data.get('reginqui_propiedad_id')
    medidor_gas_id = int(query.data.split("_")[2]) if query.data != 'medgas_sel_none' else None
    actualizar_datos_inquilino(chat_id_reg, medidor_asignado_gas_id=medidor_gas_id)

    await query.edit_message_text(
        escape_markdown_v2("Registro completo para el inquilino."), reply_markup=teclado_admin_inquilinos(), parse_mode='MarkdownV2'
    )
    await send_welcome_and_wifi_key_to_inquilino(context, chat_id_reg, propiedad_id)
    return ConversationHandler.END

async def send_welcome_and_wifi_key_to_inquilino(context: ContextTypes.DEFAULT_TYPE, chat_id_inquilino, propiedad_id):
    """Envía un mensaje de bienvenida, la clave de Wi-Fi y la fecha de pago al inquilino."""
    inquilino_info = obtener_inquilino(chat_id_inquilino)
    propiedad = obtener_propiedad_por_id(propiedad_id)

    if not inquilino_info:
        logger.error(f"No se encontró información del inquilino para enviar bienvenida: {chat_id_inquilino}")
        return

    welcome_message = f"¡Hola {escape_markdown_v2(inquilino_info[1])}! Tu registro ha sido completado por el administrador.\n\n"

    if inquilino_info[3]: # fecha_ingreso
        try:
            fecha_ingreso_dt = datetime.strptime(inquilino_info[3], '%Y-%m-%d')
            dia_pago = fecha_ingreso_dt.day
            welcome_message += f"Tu fecha de pago mensual es el día {dia_pago} de cada mes.\n\n"
        except ValueError:
            logger.error(f"Fecha de ingreso inválida para inquilino {chat_id_inquilino}: {inquilino_info[3]}")

    if propiedad:
        wifi_ssid = propiedad[3] if propiedad[3] else 'No asignado'
        wifi_password = propiedad[4] if propiedad[4] else 'No asignado'
        welcome_message += f"Detalles de tu propiedad:\n" \
                           f"  - Red Wi-Fi (SSID): `{escape_markdown_v2(wifi_ssid)}`\n" \
                           f"  - Contraseña Wi-Fi: `{escape_markdown_v2(wifi_password)}`\n\n"
    
    welcome_message += "Con este bot podrás:\n" \
                       "- Consultar tu saldo y pagos.\n" \
                       "- Amortizar tu alquiler.\n" \
                       "- Enviar quejas o sugerencias.\n" \
                       "- Ver los detalles de tu propiedad.\n\n" \
                       "Usa /start para acceder a tu menú."

    try:
        await context.bot.send_message(
            chat_id=chat_id_inquilino,
            text=escape_markdown_v2(welcome_message),
            parse_mode='MarkdownV2'
        )
        logger.info(f"Mensaje de bienvenida y Wi-Fi enviado a inquilino {chat_id_inquilino}.")
    except Exception as e:
        logger.error(f"Error al enviar mensaje de bienvenida a {chat_id_inquilino}: {e}")

async def handle_amortizar_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Maneja el click en 'Amortizar alquiler'."""
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat.id
    inquilino = obtener_inquilino(chat_id)
    if inquilino and inquilino[3] is not None:
        await query.edit_message_text(
            escape_markdown_v2("Ingresa el monto que deseas amortizar:"),
            reply_markup=boton_volver_menu('inquilino'), parse_mode='MarkdownV2'
        )
        return INQ_AMORTIZAR_MONTO
    else:
        await query.edit_message_text(
            escape_markdown_v2("No puedes amortizar aún. Tu registro está pendiente o incompleto. Contacta al administrador."),
            reply_markup=teclado_inquilino(), parse_mode='MarkdownV2'
        )
        return ConversationHandler.END

async def inq_amortizar_monto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Pide el monto a amortizar."""
    message_editor = update.message.reply_text if update.message else update.callback_query.edit_message_text
    if update.callback_query: await update.callback_query.answer()

    chat_id = update.effective_chat.id
    texto = update.effective_message.text.strip()
    try:
        monto_pago = float(texto)
        if monto_pago <= 0:
            raise ValueError("El monto debe ser un número positivo.")
    except ValueError:
        await update.message.reply_text(escape_markdown_v2("Monto inválido, ingresa un número positivo. Intenta de nuevo:"),
                                        reply_markup=boton_volver_menu('inquilino'), parse_mode='MarkdownV2')
        return INQ_AMORTIZAR_MONTO
    context.user_data['monto_amortizar'] = monto_pago
    await update.message.reply_text( # Usar reply_text porque es respuesta a un mensaje de texto
        escape_markdown_v2("Ahora, por favor, envía una *foto del comprobante de pago*."),
        parse_mode='MarkdownV2',
        reply_markup=boton_volver_menu('inquilino')
    )
    return INQ_AMORTIZAR_COMPROBANTE

async def inq_amortizar_comprobante(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Recibe el comprobante de pago y registra el pago como pendiente."""
    chat_id = update.effective_chat.id
    monto_amortizar = context.user_data.get('monto_amortizar')
    if not monto_amortizar:
        await update.message.reply_text(escape_markdown_v2("Error: No se encontró el monto a amortizar. Por favor, vuelve a intentar desde el menú."),
                                        reply_markup=teclado_inquilino(), parse_mode='MarkdownV2')
        return ConversationHandler.END

    if update.message.photo:
        comprobante_file_id = update.message.photo[-1].file_id
        comprobante_info_for_db = f"Foto ID: {comprobante_file_id}"
    else:
        await update.message.reply_text(escape_markdown_v2("Por favor, envía una *foto* del comprobante. Intenta de nuevo:"),
                                        parse_mode='MarkdownV2',
                                        reply_markup=boton_volver_menu('inquilino'))
        return INQ_AMORTIZAR_COMPROBANTE

    inquilino = obtener_inquilino(chat_id)
    saldo_actual_inquilino = inquilino[6] if inquilino and inquilino[6] is not None else 0.0
    saldo_despues_pago_simulado = saldo_actual_inquilino - monto_amortizar
    
    # Registrar el pago y obtener su ID
    cursor.execute(
        "INSERT INTO pagos(chat_id, fecha_pago, monto_pagado, saldo_restante, comprobante, confirmado) VALUES (?, ?, ?, ?, ?, ?)",
        (chat_id, datetime.now().strftime("%Y-%m-%d"), monto_amortizar, saldo_despues_pago_simulado, comprobante_info_for_db, 0)
    )
    conn.commit()
    pago_id = cursor.lastrowid # Obtener el ID del pago recién insertado
    logger.info(f"Pago de {monto_amortizar} registrado para {chat_id}. Saldo pendiente de confirmación. Pago ID: {pago_id}")

    await update.message.reply_text(
        escape_markdown_v2(f"Tu pago de {monto_amortizar:.2f} Bs. ha sido registrado y está *pendiente de confirmación* por el administrador."),
        parse_mode='MarkdownV2',
        reply_markup=teclado_inquilino()
    )
    
    for admin_id in ADMIN_IDS:
        try:
            inquilino_nombre = inquilino[1] if inquilino else chat_id
            
            # Botón para confirmar directamente
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Confirmar Pago", callback_data=f"confirmpago_{pago_id}")]
            ])

            await context.bot.send_message(
                chat_id=admin_id,
                text=escape_markdown_v2(f"🚨 *Nuevo pago pendiente de confirmación:*\n"
                     f"Inquilino: {escape_markdown_v2(inquilino_nombre)} (ID: {chat_id})\n"
                     f"Monto: {monto_amortizar:.2f} Bs."),
                parse_mode='MarkdownV2'
            )
            if update.message.photo:
                await context.bot.send_photo(
                    chat_id=admin_id,
                    photo=comprobante_file_id,
                    caption=escape_markdown_v2(f"Comprobante de pago de {escape_markdown_v2(inquilino_nombre)} para {monto_amortizar:.2f} Bs."),
                    reply_markup=keyboard, # Añadir el botón al comprobante
                    parse_mode='MarkdownV2'
                )
            else: # Si no hay foto, enviar el botón en un mensaje separado
                 await context.bot.send_message(
                    chat_id=admin_id,
                    text=escape_markdown_v2(f"Comprobante de pago de {escape_markdown_v2(inquilino_nombre)} para {monto_amortizar:.2f} Bs."),
                    reply_markup=keyboard,
                    parse_mode='MarkdownV2'
                )

        except Exception as e:
            logger.error(f"Error al notificar al admin {admin_id} sobre pago pendiente: {e}")

    return ConversationHandler.END

async def handle_admin_confirmar_pagos_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Muestra la lista de pagos pendientes de confirmación."""
    query = update.callback_query
    await query.answer()
    pagos_pendientes = obtener_pagos_pendientes()
    if not pagos_pendientes:
        await query.edit_message_text(
            escape_markdown_v2("No hay pagos pendientes de confirmación."),
            reply_markup=teclado_admin_comunicacion(), parse_mode='MarkdownV2'
        )
        return ConversationHandler.END

    buttons = []
    for p_id, chat_id, nombre_inquilino, fecha_pago, monto, saldo_restante, comprobante in pagos_pendientes:
        buttons.append([InlineKeyboardButton(escape_markdown_v2(f"ID Pago: {p_id} - {nombre_inquilino} ({monto:.2f} Bs.)"), callback_data=f"confirmpago_{p_id}")])
    buttons.append([InlineKeyboardButton("Volver", callback_data='admin_menu_comunicacion')])
    await query.edit_message_text(
        escape_markdown_v2("Selecciona un pago para confirmar:"),
        reply_markup=InlineKeyboardMarkup(buttons), parse_mode='MarkdownV2'
    )
    return ADMIN_CONFIRM_PAGO_SELECT

async def admin_confirm_pago_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Muestra los detalles de un pago pendiente y pide confirmación."""
    query = update.callback_query
    await query.answer()
    pago_id = int(query.data.split("_")[1])
    context.user_data['pago_a_confirmar_id'] = pago_id

    cursor.execute("SELECT p.chat_id, i.nombre, p.fecha_pago, p.monto_pagado, p.saldo_restante, p.comprobante, i.saldo FROM pagos p JOIN inquilinos i ON p.chat_id = i.chat_id WHERE p.id = ?", (pago_id,))
    pago_info = cursor.fetchone()

    if not pago_info:
        await query.edit_message_text(escape_markdown_v2("Pago no encontrado. Puede que ya haya sido confirmado o eliminado."),
                                      reply_markup=teclado_admin_comunicacion(), parse_mode='MarkdownV2')
        return ConversationHandler.END

    chat_id_inquilino, nombre_inquilino, fecha_pago, monto_pagado, saldo_restante_simulado, comprobante_info_db, saldo_actual_inquilino_db = pago_info
    
    nuevo_saldo_real = saldo_actual_inquilino_db - monto_pagado

    context.user_data['pago_info_confirm'] = {
        'chat_id': chat_id_inquilino,
        'monto_pagado': monto_pagado,
        'saldo_restante': nuevo_saldo_real
    }

    comprobante_file_id = None
    if comprobante_info_db and comprobante_info_db.startswith("Foto ID: "):
        comprobante_file_id = comprobante_info_db.replace("Foto ID: ", "")

    if comprobante_file_id:
        try:
            await context.bot.send_photo(
                chat_id=query.message.chat.id,
                photo=comprobante_file_id,
                caption=escape_markdown_v2(f"Comprobante enviado por {escape_markdown_v2(nombre_inquilino)} para el pago de {monto_pagado:.2f} Bs."),
                parse_mode='MarkdownV2'
            )
        except Exception as e:
            logger.error(f"Error al enviar la foto del comprobante {comprobante_file_id}: {e}")
            await context.bot.send_message(
                chat_id=query.message.chat.id,
                text=escape_markdown_v2(f"No se pudo mostrar la imagen del comprobante (ID: {comprobante_file_id}). Error: {str(e)}"),
                parse_mode='MarkdownV2'
            )

    keyboard = [
        [InlineKeyboardButton("Confirmar Pago", callback_data='confirm_pago_yes')],
        [InlineKeyboardButton("Cancelar", callback_data='confirm_pago_no')]
    ]
    await query.edit_message_text(
        escape_markdown_v2(f"Detalles del pago:\n"
        f"- Inquilino: {escape_markdown_v2(nombre_inquilino)} (ID: {chat_id_inquilino})\n"
        f"- Fecha: {fecha_pago}\n"
        f"- Monto: {monto_pagado:.2f} Bs.\n"
        f"- Saldo actual del inquilino (antes de este pago): {saldo_actual_inquilino_db:.2f} Bs.\n"
        f"- Saldo del inquilino si se confirma este pago: {nuevo_saldo_real:.2f} Bs.\n\n"
        f"¿Deseas confirmar este pago?"),
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='MarkdownV2'
    )
    return ADMIN_CONFIRM_PAGO_CONFIRM

async def admin_confirm_pago_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Confirma o cancela el pago pendiente."""
    query = update.callback_query
    await query.answer()
    pago_id = context.user_data.get('pago_a_confirmar_id')
    pago_info = context.user_data.get('pago_info_confirm')

    if not pago_id or not pago_info:
        await query.edit_message_text(escape_markdown_v2("Error: Información del pago no encontrada."), reply_markup=teclado_admin_comunicacion(), parse_mode='MarkdownV2')
        return ConversationHandler.END

    chat_id_inquilino = pago_info['chat_id']
    monto_pagado = pago_info['monto_pagado']
    saldo_real_despues_pago = pago_info['saldo_restante']

    if query.data == 'confirm_pago_yes':
        confirmar_pago_db(pago_id, chat_id_inquilino, monto_pagado, saldo_real_despues_pago)
        await query.edit_message_text(escape_markdown_v2("Pago confirmado y saldo actualizado."), reply_markup=teclado_admin_comunicacion(), parse_mode='MarkdownV2')
        try:
            await context.bot.send_message(
                chat_id=chat_id_inquilino,
                text=escape_markdown_v2(f"✅ Tu pago de {monto_pagado:.2f} Bs. ha sido *confirmado* por la administración.\n"
                     f"Tu nuevo saldo pendiente es: {saldo_real_despues_pago:.2f} Bs."),
                parse_mode='MarkdownV2'
            )
        except Exception as e:
            logger.error(f"Error al notificar al inquilino {chat_id_inquilino} sobre pago confirmado: {e}")
    else:
        await query.edit_message_text(escape_markdown_v2("Confirmación de pago cancelada."), reply_markup=teclado_admin_comunicacion(), parse_mode='MarkdownV2')

    del context.user_data['pago_a_confirmar_id']
    if 'pago_info_confirm' in context.user_data: del context.user_data['pago_info_confirm']
    return ConversationHandler.END


async def handle_admin_quejas_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Muestra las quejas pendientes y da opción a marcarlas como resueltas."""
    query = update.callback_query
    await query.answer()
    quejas_pendientes = obtener_quejas_pendientes()
    if not quejas_pendientes:
        await query.edit_message_text(
            escape_markdown_v2("No hay quejas o sugerencias pendientes."),
            reply_markup=teclado_admin_comunicacion(), parse_mode='MarkdownV2'
        )
        return ConversationHandler.END

    texto = "Quejas/Sugerencias pendientes:\n\n"
    buttons = []
    for q_id, q_chat_id, i_nombre, q_fecha, q_texto in quejas_pendientes:
        texto += f"*ID:* {q_id}\n"
        texto += f"*De:* {escape_markdown_v2(i_nombre)} (Chat ID: {q_chat_id})\n"
        texto += f"*Fecha:* {q_fecha}\n"
        texto += f"*Mensaje:* {escape_markdown_v2(q_texto)}\n\n"
        buttons.append([InlineKeyboardButton(escape_markdown_v2(f"Marcar como resuelta Queja ID: {q_id}"), callback_data=f"markqueja_{q_id}")])
    buttons.append([InlineKeyboardButton("Volver", callback_data='admin_menu_comunicacion')])
    await query.edit_message_text(escape_markdown_v2(texto), reply_markup=InlineKeyboardMarkup(buttons), parse_mode='MarkdownV2')
    return ADMIN_MARK_QUEJA_RESOLVED_SELECT

async def admin_mark_queja_resolved_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Pide confirmación para marcar una queja como resuelta."""
    query = update.callback_query
    await query.answer()
    queja_id = int(query.data.split("_")[1])
    context.user_data['queja_a_resolver_id'] = queja_id

    keyboard = [
        [InlineKeyboardButton("Sí, marcar como resuelta", callback_data='confirm_resolve_queja')],
        [InlineKeyboardButton("No, cancelar", callback_data='cancel_resolve_queja')]
    ]
    await query.edit_message_text(
        escape_markdown_v2(f"¿Estás seguro de que quieres marcar la queja ID {queja_id} como resuelta?"),
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='MarkdownV2'
    )
    return ADMIN_MARK_QUEJA_RESOLVED_CONFIRM

async def admin_mark_queja_resolved_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Confirma y marca la queja como resuelta."""
    query = update.callback_query
    await query.answer()
    queja_id = context.user_data.get('queja_a_resolver_id')

    if query.data == 'confirm_resolve_queja':
        marcar_queja_resuelto(queja_id)
        await query.edit_message_text(escape_markdown_v2(f"Queja ID {queja_id} marcada como resuelta."),
                                      reply_markup=teclado_admin_comunicacion(), parse_mode='MarkdownV2')
    else:
        await query.edit_message_text(escape_markdown_v2("Operación cancelada."), reply_markup=teclado_admin_comunicacion(), parse_mode='MarkdownV2')

    if 'queja_a_resolver_id' in context.user_data: del context.user_data['queja_a_resolver_id']
    return ConversationHandler.END


async def handle_admin_reg_factura_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Maneja el click en 'Registrar factura' y pide la propiedad."""
    query = update.callback_query
    await query.answer()
    propiedades = obtener_propiedades()
    if not propiedades:
        await query.edit_message_text(escape_markdown_v2("No hay propiedades registradas para asignar la factura. Por favor, registra una propiedad primero."),
                                      reply_markup=teclado_admin_facturacion(), parse_mode='MarkdownV2')
        return ConversationHandler.END
    buttons = [[InlineKeyboardButton(escape_markdown_v2(p[1]), callback_data=f"factprop_{p[0]}")] for p in propiedades]
    buttons.append([InlineKeyboardButton("Volver", callback_data='admin_menu_facturacion')])
    await query.edit_message_text(escape_markdown_v2("Selecciona la propiedad para esta factura:"),
                                  reply_markup=InlineKeyboardMarkup(buttons), parse_mode='MarkdownV2')
    return ADMIN_REG_FACTURA_PROPIEDAD

async def admin_reg_factura_propiedad(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Maneja la selección de propiedad para la factura y pide el tipo de servicio."""
    query = update.callback_query
    await query.answer()
    propiedad_id = int(query.data.split("_")[1])
    context.user_data['factura_propiedad_id'] = propiedad_id
    await query.edit_message_text(
        escape_markdown_v2("Selecciona el tipo de servicio de la factura:"),
        reply_markup=teclado_tipos_servicio_factura(), parse_mode='MarkdownV2'
    )
    return ADMIN_REG_FACTURA_SERVICIO_TIPO

async def admin_reg_factura_servicio_tipo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Maneja la selección del tipo de servicio para la factura y pide el medidor (si aplica)."""
    query = update.callback_query
    await query.answer()
    servicio_tipo = query.data.split("_")[1]
    context.user_data['factura_servicio_tipo'] = servicio_tipo
    propiedad_id = context.user_data.get('factura_propiedad_id')

    medidores = obtener_medidores_por_propiedad(propiedad_id, servicio_tipo)
    if medidores:
        buttons = [[InlineKeyboardButton(escape_markdown_v2(m[1]), callback_data=f"factmed_{m[0]}")] for m in medidores]
        buttons.append([InlineKeyboardButton("No aplica (factura general de propiedad)", callback_data='factmed_none')])
        buttons.append([InlineKeyboardButton("Volver", callback_data='admin_menu_facturacion')])
        await query.edit_message_text(escape_markdown_v2(f"Selecciona el medidor de *{servicio_tipo.replace('_', '/').upper()}* para esta factura (si aplica):"),
                                      reply_markup=InlineKeyboardMarkup(buttons), parse_mode='MarkdownV2')
        return ADMIN_REG_FACTURA_MONTO
    else:
        context.user_data['factura_medidor_id'] = None
        context.user_data['awaiting_kwh_input'] = False
        
        message_text = escape_markdown_v2(f"No hay medidores de *{servicio_tipo.replace('_', '/').upper()}* para esta propiedad. ")
        if servicio_tipo == 'luz':
            message_text += escape_markdown_v2("Ingresa el monto de la factura de LUZ y el total de kWh (ej: 150.75,300):")
            context.user_data['awaiting_kwh_input'] = True
        else:
            message_text += escape_markdown_v2(f"Ingresa el monto de la factura de *{servicio_tipo.replace('_', '/').upper()}*:")

        await query.edit_message_text(message_text, reply_markup=boton_volver_menu('admin', 'admin_menu_facturacion'), parse_mode='MarkdownV2')
        return ADMIN_REG_FACTURA_MONTO

async def admin_reg_factura_monto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Maneja la entrada del monto de la factura y la registra."""
    message_editor = update.message.reply_text if update.message else update.callback_query.edit_message_text
    if update.callback_query: await update.callback_query.answer()

    if update.callback_query: # Si viene de la selección de medidor
        medidor_id = int(update.callback_query.data.split("_")[1]) if update.callback_query.data != 'factmed_none' else None
        context.user_data['factura_medidor_id'] = medidor_id
        servicio_tipo = context.user_data.get('factura_servicio_tipo')

        if servicio_tipo == 'luz' and medidor_id is not None:
            await update.callback_query.edit_message_text(
                escape_markdown_v2(f"Ingresa el monto de la factura de *{servicio_tipo.upper()}*. Si es de luz, ingresa también el total de kWh de la factura (ej: 150.75,300):"),
                reply_markup=boton_volver_menu('admin', 'admin_menu_facturacion'), parse_mode='MarkdownV2'
            )
            context.user_data['awaiting_kwh_input'] = True
            return ADMIN_REG_FACTURA_MONTO
        else:
            await update.callback_query.edit_message_text(
                escape_markdown_v2(f"Ingresa el monto de la factura de *{servicio_tipo.replace('_', '/').upper()}*:"),
                reply_markup=boton_volver_menu('admin', 'admin_menu_facturacion'), parse_mode='MarkdownV2'
            )
            context.user_data['awaiting_kwh_input'] = False
            return ADMIN_REG_FACTURA_MONTO

    else: # Si es la entrada del monto por texto
        texto = update.effective_message.text.strip()
        propiedad_id = context.user_data.get('factura_propiedad_id')
        servicio_tipo = context.user_data.get('factura_servicio_tipo')
        medidor_id = context.user_data.get('factura_medidor_id')
        awaiting_kwh_input = context.user_data.get('awaiting_kwh_input', False)

        monto = 0.0
        total_kwh = 0.0

        try:
            if awaiting_kwh_input and servicio_tipo == 'luz':
                parts = texto.split(',')
                if len(parts) == 2:
                    monto = float(parts[0].strip())
                    total_kwh = float(parts[1].strip())
                else:
                    raise ValueError("Formato incorrecto. Usa 'monto,kwh'.")
            else:
                monto = float(texto)
            
            if monto <= 0:
                raise ValueError("El monto debe ser positivo.")
            if total_kwh < 0:
                raise ValueError("Los kWh no pueden ser negativos.")

        except ValueError as e:
            await update.message.reply_text(escape_markdown_v2(f"Entrada inválida: {str(e)}. Ingresa un número válido (o 'monto,kwh' para luz). Intenta de nuevo:"),
                                            reply_markup=boton_volver_menu('admin', 'admin_menu_facturacion'), parse_mode='MarkdownV2')
            return ADMIN_REG_FACTURA_MONTO

        registrar_factura_db(servicio_tipo, monto, propiedad_id, medidor_id, total_kwh)
        await update.message.reply_text(escape_markdown_v2("Factura registrada."), reply_markup=teclado_admin_facturacion(), parse_mode='MarkdownV2')
        if 'awaiting_kwh_input' in context.user_data: del context.user_data['awaiting_kwh_input']
        return ConversationHandler.END


async def handle_admin_reg_lectura_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Maneja el click en 'Registrar lectura contador' y pide la propiedad."""
    query = update.callback_query
    await query.answer()
    propiedades = obtener_propiedades()
    if not propiedades:
        await query.edit_message_text(escape_markdown_v2("No hay propiedades registradas para registrar lecturas. Por favor, registra una propiedad primero."),
                                      reply_markup=teclado_admin_facturacion(), parse_mode='MarkdownV2')
        return ConversationHandler.END
    buttons = [[InlineKeyboardButton(escape_markdown_v2(p[1]), callback_data=f"lectprop_{p[0]}")] for p in propiedades]
    buttons.append([InlineKeyboardButton("Volver", callback_data='admin_menu_facturacion')])
    await query.edit_message_text(escape_markdown_v2("Selecciona la propiedad para la cual registrarás la lectura:"),
                                  reply_markup=InlineKeyboardMarkup(buttons), parse_mode='MarkdownV2')
    return ADMIN_REG_LECTURA_PROPIEDAD

async def admin_reg_lectura_propiedad(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Maneja la selección de propiedad para la lectura y muestra los medidores."""
    query = update.callback_query
    await query.answer()
    propiedad_id = int(query.data.split("_")[1])
    context.user_data['lectura_propiedad_id'] = propiedad_id

    medidores = obtener_medidores_por_propiedad(propiedad_id)
    if not medidores:
        await query.edit_message_text(escape_markdown_v2("No hay medidores registrados para esta propiedad. Por favor, añade uno primero."),
                                      reply_markup=boton_volver_menu('admin', 'admin_gestionar_propiedades'), parse_mode='MarkdownV2')
        return ConversationHandler.END

    buttons = [[InlineKeyboardButton(escape_markdown_v2(f"{m[1]} ({m[2].capitalize()})"), callback_data=f"lectmed_{m[0]}")] for m in medidores]
    buttons.append([InlineKeyboardButton("Volver", callback_data='admin_menu_facturacion')])
    await query.edit_message_text(escape_markdown_v2("Selecciona el medidor para el que registrarás la lectura:"),
                                  reply_markup=InlineKeyboardMarkup(buttons), parse_mode='MarkdownV2')
    return ADMIN_REG_LECTURA_MEDIDOR_SELECT

async def admin_reg_lectura_medidor_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Maneja la selección de medidor para la lectura y pide el valor."""
    query = update.callback_query
    await query.answer()
    medidor_id = int(query.data.split("_")[1])
    context.user_data['lectura_medidor_id'] = medidor_id
    medidor_info = obtener_medidor_por_id(medidor_id)
    medidor_nombre = medidor_info[2] if medidor_info else "desconocido"
    await query.edit_message_text(
        escape_markdown_v2(f"Ingresa la lectura para el medidor '{escape_markdown_v2(medidor_nombre)}':"),
        reply_markup=boton_volver_menu('admin', 'admin_menu_facturacion'), parse_mode='MarkdownV2'
    )
    return ADMIN_REG_LECTURA_VALOR

async def admin_reg_lectura_valor(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Maneja la entrada del valor de la lectura y la registra."""
    message_editor = update.message.reply_text if update.message else update.callback_query.edit_message_text
    if update.callback_query: await update.callback_query.answer()

    texto = update.effective_message.text.strip()
    medidor_id = context.user_data.get('lectura_medidor_id')

    if not medidor_id:
        await update.message.reply_text(escape_markdown_v2("Error: No se seleccionó un medidor. Vuelve a intentarlo."),
                                        reply_markup=teclado_admin_facturacion(), parse_mode='MarkdownV2')
        return ConversationHandler.END

    try:
        lectura = float(texto)
        if lectura < 0:
            raise ValueError("La lectura no puede ser negativa.")
    except ValueError:
        await update.message.reply_text(escape_markdown_v2("Lectura inválida. Ingresa un número válido. Intenta de nuevo:"),
                                        reply_markup=boton_volver_menu('admin', 'admin_menu_facturacion'), parse_mode='MarkdownV2')
        return ADMIN_REG_LECTURA_VALOR

    registrar_lectura_db(medidor_id, lectura)
    await update.message.reply_text(escape_markdown_v2("Lectura registrada."), reply_markup=teclado_admin_facturacion(), parse_mode='MarkdownV2')
    return ConversationHandler.END


async def handle_admin_nuevo_inquilino_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Maneja el click en 'Añadir nuevo inquilino (manual)'."""
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        escape_markdown_v2("Por favor, ingresa el nombre completo del nuevo inquilino para añadirlo manualmente:"),
        reply_markup=boton_volver_menu('admin', 'admin_menu_inquilinos'), parse_mode='MarkdownV2'
    )
    return NOMBRE

async def obtener_nombre_manual(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Obtiene el nombre del inquilino para el registro manual del admin."""
    message_editor = update.message.reply_text if update.message else update.callback_query.edit_message_text
    if update.callback_query: await update.callback_query.answer()

    nombre = update.effective_message.text.strip()
    if not nombre:
        await update.message.reply_text(escape_markdown_v2("El nombre no puede estar vacío, intenta de nuevo:"),
                                        reply_markup=boton_volver_menu('admin', 'admin_menu_inquilinos'), parse_mode='MarkdownV2')
        return NOMBRE
    context.user_data['nombre_manual'] = nombre

    await update.message.reply_text(escape_markdown_v2(f"Nombre '{escape_markdown_v2(nombre)}' guardado. Ahora ingresa el Chat ID de Telegram del inquilino (debe ser un número):"),
                                    reply_markup=boton_volver_menu('admin', 'admin_menu_inquilinos'), parse_mode='MarkdownV2')
    return REGISTRAR_CI

async def obtener_chat_id_manual(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Obtiene el Chat ID del inquilino para el registro manual del admin."""
    message_editor = update.message.reply_text if update.message else update.callback_query.edit_message_text
    if update.callback_query: await update.callback_query.answer()

    chat_id_str = update.effective_message.text.strip()
    nombre = context.user_data.get('nombre_manual')

    try:
        chat_id_nuevo = int(chat_id_str)
        if chat_id_nuevo <= 0:
            raise ValueError("El Chat ID debe ser un número positivo.")
    except ValueError:
        await update.message.reply_text(escape_markdown_v2("Chat ID inválido. Ingresa un número entero válido. Intenta de nuevo:"),
                                        reply_markup=boton_volver_menu('admin', 'admin_menu_inquilinos'), parse_mode='MarkdownV2')
        return REGISTRAR_CI

    agregar_inquilino(chat_id_nuevo, nombre, "PENDIENTE_CI")

    await update.message.reply_text(escape_markdown_v2(f"Inquilino '{escape_markdown_v2(nombre)}' con Chat ID '{chat_id_nuevo}' agregado correctamente. "
                                     "Recuerda que aún debes completar su registro (fecha de ingreso, monto, tipo, propiedad, medidor) "
                                     "desde la opción 'Completar registro de inquilino' en el menú de administrador."),
                                     reply_markup=teclado_admin_inquilinos(), parse_mode='MarkdownV2')
    return ConversationHandler.END

async def handle_admin_eliminar_inquilino_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Maneja el click en 'Eliminar inquilino' y muestra la lista."""
    query = update.callback_query
    await query.answer()
    cursor.execute("SELECT chat_id, nombre, ci FROM inquilinos")
    inquilinos = cursor.fetchall()
    if not inquilinos:
        await query.edit_message_text(
            escape_markdown_v2("No hay inquilinos para eliminar."),
            reply_markup=teclado_admin_inquilinos(), parse_mode='MarkdownV2'
        )
        return ConversationHandler.END
    buttons = [
        [InlineKeyboardButton(escape_markdown_v2(f"{nom} (CI: {ci}) - ID: {cid}"), callback_data=f"delinqui_{cid}")]
        for cid, nom, ci in inquilinos
    ]
    buttons.append([InlineKeyboardButton("Volver", callback_data='admin_menu_inquilinos')])
    await query.edit_message_text(
        escape_markdown_v2("Selecciona el inquilino a eliminar:"),
        reply_markup=InlineKeyboardMarkup(buttons), parse_mode='MarkdownV2'
    )
    return ADMIN_ELIMINAR_INQUILINO_SELECT

async def admin_eliminar_inquilino_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Maneja la selección de inquilino a eliminar y pide confirmación."""
    query = update.callback_query
    await query.answer()
    chat_id_eliminar = int(query.data.split("_")[1])
    context.user_data['eliminar_chat_id'] = chat_id_eliminar
    inquilino_info = obtener_inquilino(chat_id_eliminar)
    nombre_inquilino = inquilino_info[1] if inquilino_info else "Desconocido"

    keyboard = [
        [InlineKeyboardButton("Sí, eliminar", callback_data='confirm_del_inquilino')],
        [InlineKeyboardButton("No, cancelar", callback_data='cancel_del_inquilino')]
    ]
    await query.edit_message_text(
        escape_markdown_v2(f"¿Estás seguro de que quieres eliminar a {escape_markdown_v2(nombre_inquilino)} (Chat ID: {chat_id_eliminar}) y todos sus registros?"),
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='MarkdownV2'
    )
    return ADMIN_ELIMINAR_INQUILINO_CONFIRM

async def admin_eliminar_inquilino_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Confirma y ejecuta la eliminación del inquilino."""
    query = update.callback_query
    await query.answer()
    chat_id_eliminar = context.user_data.get('eliminar_chat_id')

    if query.data == 'confirm_del_inquilino':
        if eliminar_inquilino_db(chat_id_eliminar):
            await query.edit_message_text(escape_markdown_v2(f"Inquilino (Chat ID: {chat_id_eliminar}) eliminado correctamente."),
                                          reply_markup=teclado_admin_inquilinos(), parse_mode='MarkdownV2')
        else:
            await query.edit_message_text(escape_markdown_v2(f"Error al eliminar inquilino (Chat ID: {chat_id_eliminar}). Intenta de nuevo."),
                                          reply_markup=teclado_admin_inquilinos(), parse_mode='MarkdownV2')
    else:
        await query.edit_message_text(escape_markdown_v2("Eliminación cancelada."), reply_markup=teclado_admin_inquilinos(), parse_mode='MarkdownV2')

    return ConversationHandler.END

async def handle_admin_gestionar_propiedades_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Maneja el click en 'Gestionar propiedades'."""
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        escape_markdown_v2("Menú de gestión de propiedades:"),
        reply_markup=teclado_gestionar_propiedades(), parse_mode='MarkdownV2'
    )
    return ADMIN_PROPIEDADES_MENU

async def admin_ver_propiedades_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Muestra la lista de propiedades registradas."""
    query = update.callback_query
    await query.answer()
    propiedades = obtener_propiedades()
    if not propiedades:
        await query.edit_message_text(escape_markdown_v2("No hay propiedades registradas."), reply_markup=teclado_gestionar_propiedades(), parse_mode='MarkdownV2')
        return ConversationHandler.END

    texto = "Propiedades registradas:\n\n"
    for p_id, nombre, direccion, wifi_ssid, wifi_password in propiedades:
        texto += f"*ID:* {p_id}\n"
        texto += f"*Nombre:* {escape_markdown_v2(nombre)}\n"
        texto += f"*Dirección:* {escape_markdown_v2(direccion)}\n"
        texto += f"  *SSID Wi-Fi:* `{escape_markdown_v2(wifi_ssid if wifi_ssid else 'No asignado')}`\n"
        texto += f"  *Contraseña Wi-Fi:* `{escape_markdown_v2(wifi_password if wifi_password else 'No asignado')}`\n"
        medidores = obtener_medidores_por_propiedad(p_id)
        if medidores:
            texto += "* Medidores:*\n"
            for m_id, m_nombre, m_tipo in medidores:
                texto += f"    - ID: {m_id}, Nombre: {escape_markdown_v2(m_nombre)} (Tipo: {escape_markdown_v2(m_tipo.replace('_', '/').capitalize())})\n"
        texto += "\n"
    await query.edit_message_text(escape_markdown_v2(texto), reply_markup=teclado_gestionar_propiedades(), parse_mode='MarkdownV2')
    return ConversationHandler.END

async def handle_admin_add_propiedad_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Inicia el flujo para añadir una nueva propiedad."""
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        escape_markdown_v2("Ingresa el nombre de la nueva propiedad (ej. Casa Blanca):"),
        reply_markup=boton_volver_menu('admin', 'admin_propiedades'), parse_mode='MarkdownV2'
    )
    return ADMIN_ADD_PROPIEDAD_NOMBRE

async def admin_add_propiedad_nombre(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Obtiene el nombre de la propiedad."""
    message_editor = update.message.reply_text if update.message else update.callback_query.edit_message_text
    if update.callback_query: await update.callback_query.answer()

    nombre = update.effective_message.text.strip()
    if not nombre:
        await update.message.reply_text(escape_markdown_v2("El nombre no puede estar vacío. Intenta de nuevo:"),
                                        reply_markup=boton_volver_menu('admin', 'admin_propiedades'), parse_mode='MarkdownV2')
        return ADMIN_ADD_PROPIEDAD_NOMBRE
    context.user_data['nueva_propiedad_nombre'] = nombre
    await update.message.reply_text(escape_markdown_v2("Ingresa la dirección de la propiedad (ej. Calle Falsa 123):"),
                                    reply_markup=boton_volver_menu('admin', 'admin_propiedades'), parse_mode='MarkdownV2')
    return ADMIN_ADD_PROPIEDAD_DIRECCION

async def admin_add_propiedad_direccion(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Obtiene la dirección de la propiedad."""
    message_editor = update.message.reply_text if update.message else update.callback_query.edit_message_text
    if update.callback_query: await update.callback_query.answer()

    direccion = update.effective_message.text.strip()
    if not direccion:
        await update.message.reply_text(escape_markdown_v2("La dirección no puede estar vacía. Intenta de nuevo:"),
                                        reply_markup=boton_volver_menu('admin', 'admin_propiedades'), parse_mode='MarkdownV2')
        return ADMIN_ADD_PROPIEDAD_DIRECCION
    context.user_data['nueva_propiedad_direccion'] = direccion
    await update.message.reply_text(escape_markdown_v2("Ingresa el nombre de la red Wi-Fi (SSID) para esta propiedad (o 'N/A' si no aplica):"),
                                    reply_markup=boton_volver_menu('admin', 'admin_propiedades'), parse_mode='MarkdownV2')
    return ADMIN_ADD_PROPIEDAD_SSID

async def admin_add_propiedad_ssid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Obtiene el SSID de la propiedad."""
    message_editor = update.message.reply_text if update.message else update.callback_query.edit_message_text
    if update.callback_query: await update.callback_query.answer()

    ssid = update.effective_message.text.strip()
    context.user_data['nueva_propiedad_ssid'] = ssid if ssid.upper() != 'N/A' else None
    await update.message.reply_text(escape_markdown_v2("Ingresa la contraseña de Wi-Fi para esta propiedad (o 'N/A' si no aplica):"),
                                    reply_markup=boton_volver_menu('admin', 'admin_propiedades'), parse_mode='MarkdownV2')
    return ADMIN_ADD_PROPIEDAD_WIFI

async def admin_add_propiedad_wifi(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Obtiene la contraseña de Wi-Fi y finaliza el registro de propiedad."""
    message_editor = update.message.reply_text if update.message else update.callback_query.edit_message_text
    if update.callback_query: await update.callback_query.answer()

    wifi_password = update.effective_message.text.strip()
    nombre = context.user_data.get('nueva_propiedad_nombre')
    direccion = context.user_data.get('nueva_propiedad_direccion')
    wifi_ssid = context.user_data.get('nueva_propiedad_ssid')
    wifi_password_final = wifi_password if wifi_password.upper() != 'N/A' else None

    if agregar_propiedad(nombre, direccion, wifi_ssid, wifi_password_final):
        await update.message.reply_text(escape_markdown_v2(f"Propiedad '{escape_markdown_v2(nombre)}' agregada correctamente."),
                                        reply_markup=teclado_gestionar_propiedades(), parse_mode='MarkdownV2')
    else:
        await update.message.reply_text(escape_markdown_v2(f"Error al agregar propiedad '{escape_markdown_v2(nombre)}'. Puede que ya exista un nombre igual."),
                                        reply_markup=teclado_gestionar_propiedades(), parse_mode='MarkdownV2')
    return ConversationHandler.END

async def handle_admin_del_propiedad_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Inicia el flujo para eliminar una propiedad."""
    query = update.callback_query
    await query.answer()
    propiedades = obtener_propiedades()
    if not propiedades:
        await query.edit_message_text(escape_markdown_v2("No hay propiedades para eliminar."), reply_markup=teclado_gestionar_propiedades(), parse_mode='MarkdownV2')
        return ConversationHandler.END

    buttons = [[InlineKeyboardButton(escape_markdown_v2(p[1]), callback_data=f"delprop_{p[0]}")] for p in propiedades]
    buttons.append([InlineKeyboardButton("Volver", callback_data='admin_gestionar_propiedades')])
    await query.edit_message_text(escape_markdown_v2("Selecciona la propiedad a eliminar:"),
                                  reply_markup=InlineKeyboardMarkup(buttons), parse_mode='MarkdownV2')
    return ADMIN_DEL_PROPIEDAD_SELECT

async def admin_del_propiedad_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Confirma la eliminación de la propiedad."""
    query = update.callback_query
    await query.answer()
    propiedad_id = int(query.data.split("_")[1])
    context.user_data['propiedad_a_eliminar_id'] = propiedad_id
    propiedad_info = obtener_propiedad_por_id(propiedad_id)
    nombre_propiedad = propiedad_info[1] if propiedad_info else "Desconocida"

    keyboard = [
        [InlineKeyboardButton("Sí, eliminar", callback_data='confirm_del_propiedad')],
        [InlineKeyboardButton("No, cancelar", callback_data='cancel_del_propiedad')]
    ]
    await query.edit_message_text(
        escape_markdown_v2(f"¿Estás seguro de que quieres eliminar la propiedad '{escape_markdown_v2(nombre_propiedad)}' y todos sus medidores, facturas y desvincular inquilinos?"),
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='MarkdownV2'
    )
    return ADMIN_DEL_PROPIEDAD_CONFIRM

async def admin_del_propiedad_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ejecuta la eliminación de la propiedad."""
    query = update.callback_query
    await query.answer()
    propiedad_id = context.user_data.get('propiedad_a_eliminar_id')

    if query.data == 'confirm_del_propiedad':
        if eliminar_propiedad_db(propiedad_id):
            await query.edit_message_text(escape_markdown_v2("Propiedad eliminada correctamente."),
                                          reply_markup=teclado_gestionar_propiedades(), parse_mode='MarkdownV2')
        else:
            await query.edit_message_text(escape_markdown_v2("Error al eliminar la propiedad. Intenta de nuevo."),
                                          reply_markup=teclado_gestionar_propiedades(), parse_mode='MarkdownV2')
    else:
        await query.edit_message_text(escape_markdown_v2("Eliminación de propiedad cancelada."), reply_markup=teclado_gestionar_propiedades(), parse_mode='MarkdownV2')
    return ConversationHandler.END

async def handle_admin_add_medidor_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Inicia el flujo para añadir un medidor a una propiedad."""
    query = update.callback_query
    await query.answer()
    propiedades = obtener_propiedades()
    if not propiedades:
        await query.edit_message_text(escape_markdown_v2("No hay propiedades a las que añadir medidores. Por favor, añade una propiedad primero."),
                                      reply_markup=teclado_gestionar_propiedades(), parse_mode='MarkdownV2')
        return ConversationHandler.END

    buttons = [[InlineKeyboardButton(escape_markdown_v2(p[1]), callback_data=f"addmedprop_{p[0]}")] for p in propiedades]
    buttons.append([InlineKeyboardButton("Volver", callback_data='admin_gestionar_propiedades')])
    await query.edit_message_text(escape_markdown_v2("Selecciona la propiedad a la que añadir un medidor:"),
                                  reply_markup=InlineKeyboardMarkup(buttons), parse_mode='MarkdownV2')
    return ADMIN_ADD_MEDIDOR_PROPIEDAD_SELECT

async def admin_add_medidor_propiedad_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Maneja la selección de propiedad para añadir medidor."""
    query = update.callback_query
    await query.answer()
    propiedad_id = int(query.data.split("_")[1])
    context.user_data['medidor_propiedad_id'] = propiedad_id
    propiedad_info = obtener_propiedad_por_id(propiedad_id)
    nombre_propiedad = propiedad_info[1] if propiedad_info else "Desconocida"

    await query.edit_message_text(
        escape_markdown_v2(f"Ingresa el nombre del nuevo medidor para '{escape_markdown_v2(nombre_propiedad)}' (ej. Medidor 1, Medidor Cocina):"),
        reply_markup=boton_volver_menu('admin', 'admin_propiedades'), parse_mode='MarkdownV2'
    )
    return ADMIN_ADD_MEDIDOR_NOMBRE

async def admin_add_medidor_nombre(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Obtiene el nombre del medidor y pide el tipo de servicio."""
    message_editor = update.message.reply_text if update.message else update.callback_query.edit_message_text
    if update.callback_query: await update.callback_query.answer()

    nombre_medidor = update.effective_message.text.strip()
    propiedad_id = context.user_data.get('medidor_propiedad_id')

    if not nombre_medidor:
        await update.message.reply_text(escape_markdown_v2("El nombre del medidor no puede estar vacío. Intenta de nuevo:"),
                                        reply_markup=boton_volver_menu('admin', 'admin_propiedades'), parse_mode='MarkdownV2')
        return ADMIN_ADD_MEDIDOR_NOMBRE
    if not propiedad_id:
        await update.message.reply_text(escape_markdown_v2("Error: No se seleccionó una propiedad para el medidor. Vuelve a intentarlo."),
                                        reply_markup=teclado_gestionar_propiedades(), parse_mode='MarkdownV2')
        return ConversationHandler.END
    context.user_data['nuevo_medidor_nombre'] = nombre_medidor
    await update.message.reply_text(
        escape_markdown_v2("Selecciona el tipo de servicio de este medidor (Luz, Agua, Gas, Internet/TV):"),
        reply_markup=teclado_tipos_servicio_factura(), parse_mode='MarkdownV2'
    )
    return ADMIN_ADD_MEDIDOR_TIPO

async def admin_add_medidor_tipo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Obtiene el tipo de servicio del medidor y lo registra."""
    query = update.callback_query
    await query.answer()
    tipo_servicio = query.data.split("_")[1]
    nombre_medidor = context.user_data.get('nuevo_medidor_nombre')
    propiedad_id = context.user_data.get('medidor_propiedad_id')

    if agregar_medidor(propiedad_id, nombre_medidor, tipo_servicio):
        await query.edit_message_text(escape_markdown_v2(f"Medidor '{escape_markdown_v2(nombre_medidor)}' ({escape_markdown_v2(tipo_servicio.replace('_', '/').capitalize())}) agregado correctamente a la propiedad."),
                                      reply_markup=teclado_gestionar_propiedades(), parse_mode='MarkdownV2')
    else:
        await query.edit_message_text(escape_markdown_v2(f"Error al agregar medidor '{escape_markdown_v2(nombre_medidor)}'. Puede que ya exista un medidor con ese nombre en esta propiedad."),
                                      reply_markup=teclado_gestionar_propiedades(), parse_mode='MarkdownV2')
    return ConversationHandler.END


# --- Handlers para enviar avisos ---

async def handle_admin_send_notice_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Maneja el click en 'Enviar Aviso' y pide el alcance."""
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        escape_markdown_v2("¿A quién deseas enviar el aviso?"),
        reply_markup=teclado_send_notice_scope(), parse_mode='MarkdownV2'
    )
    return ADMIN_SEND_NOTICE_SCOPE

async def admin_send_notice_scope_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Maneja la selección del alcance del aviso (propiedad o inquilino específico)."""
    query = update.callback_query
    await query.answer()
    scope = query.data.split("_")[2]
    context.user_data['notice_scope'] = scope

    if scope == 'property':
        propiedades = obtener_propiedades()
        if not propiedades:
            await query.edit_message_text(escape_markdown_v2("No hay propiedades registradas para enviar avisos. Por favor, registra una propiedad primero."),
                                          reply_markup=teclado_admin_comunicacion(), parse_mode='MarkdownV2')
            return ConversationHandler.END
        buttons = [[InlineKeyboardButton(escape_markdown_v2(p[1]), callback_data=f"noticeprop_{p[0]}")] for p in propiedades]
        buttons.append([InlineKeyboardButton("Volver", callback_data='admin_menu_comunicacion')])
        await query.edit_message_text(escape_markdown_v2("Selecciona la propiedad a la que enviar el aviso:"),
                                      reply_markup=InlineKeyboardMarkup(buttons), parse_mode='MarkdownV2')
        return ADMIN_SEND_NOTICE_PROPERTY_SELECT
    elif scope == 'single_inquilino':
        inquilinos = obtener_todos_los_inquilinos()
        if not inquilinos:
            await query.edit_message_text(escape_markdown_v2("No hay inquilinos registrados para enviar avisos. Por favor, registra uno primero."),
                                          reply_markup=teclado_admin_comunicacion(), parse_mode='MarkdownV2')
            return ConversationHandler.END
        buttons = [[InlineKeyboardButton(escape_markdown_v2(f"{i[1]} (ID: {i[0]})"), callback_data=f"noticeinq_{i[0]}")] for i in inquilinos]
        buttons.append([InlineKeyboardButton("Volver", callback_data='admin_menu_comunicacion')])
        await query.edit_message_text(escape_markdown_v2("Selecciona el inquilino al que enviar el aviso:"),
                                      reply_markup=InlineKeyboardMarkup(buttons), parse_mode='MarkdownV2')
        return ADMIN_SEND_NOTICE_INQUILINO_SELECT
    else:
        await query.edit_message_text(escape_markdown_v2("Opción inválida. Intenta de nuevo."), reply_markup=teclado_send_notice_scope(), parse_mode='MarkdownV2')
        return ADMIN_SEND_NOTICE_SCOPE

async def admin_send_notice_property_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Maneja la selección de propiedad para enviar aviso."""
    query = update.callback_query
    await query.answer()
    propiedad_id = int(query.data.split("_")[1])
    context.user_data['notice_target_id'] = propiedad_id
    propiedad_info = obtener_propiedad_por_id(propiedad_id)
    nombre_propiedad = propiedad_info[1] if propiedad_info else "Desconocida"
    await query.edit_message_text(
        escape_markdown_v2(f"Escribe el mensaje del aviso para todos los inquilinos de '{escape_markdown_v2(nombre_propiedad)}':"),
        reply_markup=boton_volver_menu('admin', 'admin_menu_comunicacion'), parse_mode='MarkdownV2'
    )
    return ADMIN_SEND_NOTICE_MESSAGE

async def admin_send_notice_inquilino_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Maneja la selección de inquilino para enviar aviso."""
    query = update.callback_query
    await query.answer()
    inquilino_chat_id = int(query.data.split("_")[1])
    context.user_data['notice_target_id'] = inquilino_chat_id
    inquilino_info = obtener_inquilino(inquilino_chat_id)
    nombre_inquilino = inquilino_info[1] if inquilino_info else "Desconocido"
    await query.edit_message_text(
        escape_markdown_v2(f"Escribe el mensaje del aviso para '{escape_markdown_v2(nombre_inquilino)}':"),
        reply_markup=boton_volver_menu('admin', 'admin_menu_comunicacion'), parse_mode='MarkdownV2'
    )
    return ADMIN_SEND_NOTICE_MESSAGE

async def admin_send_notice_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Envía el aviso al/los inquilino/s seleccionado/s."""
    message_editor = update.message.reply_text if update.message else update.callback_query.edit_message_text
    if update.callback_query: await update.callback_query.answer()

    notice_message = update.effective_message.text.strip()
    scope = context.user_data.get('notice_scope')
    target_id = context.user_data.get('notice_target_id')

    if not notice_message:
        await update.message.reply_text(escape_markdown_v2("El mensaje del aviso no puede estar vacío. Intenta de nuevo:"),
                                        reply_markup=boton_volver_menu('admin', 'admin_menu_comunicacion'), parse_mode='MarkdownV2')
        return ADMIN_SEND_NOTICE_MESSAGE

    sent_count = 0
    if scope == 'property':
        inquilinos_en_propiedad = obtener_inquilinos_por_propiedad(target_id)
        if not inquilinos_en_propiedad:
            await update.message.reply_text(escape_markdown_v2("No hay inquilinos en esa propiedad para enviar el aviso."),
                                            reply_markup=teclado_admin_comunicacion(), parse_mode='MarkdownV2')
            return ConversationHandler.END
        for chat_id, nombre_inquilino, _ in inquilinos_en_propiedad:
            try:
                await context.bot.send_message(chat_id=chat_id, text=escape_markdown_v2(f"**AVISO DE LA ADMINISTRACIÓN**\n\n{escape_markdown_v2(notice_message)}"), parse_mode='MarkdownV2')
                sent_count += 1
                logger.info(f"Aviso enviado a inquilino {escape_markdown_v2(nombre_inquilino)} ({chat_id}) en propiedad {target_id}.")
            except Exception as e:
                logger.error(f"Error al enviar aviso a inquilino {escape_markdown_v2(nombre_inquilino)} ({chat_id}): {e}")
        await update.message.reply_text(escape_markdown_v2(f"Aviso enviado a {sent_count} inquilino(s) de la propiedad."),
                                        reply_markup=teclado_admin_comunicacion(), parse_mode='MarkdownV2')
    elif scope == 'single_inquilino':
        try:
            await context.bot.send_message(chat_id=target_id, text=escape_markdown_v2(f"**AVISO DE LA ADMINISTRACIÓN**\n\n{escape_markdown_v2(notice_message)}"), parse_mode='MarkdownV2')
            sent_count += 1
            logger.info(f"Aviso enviado a inquilino específico {target_id}.")
            await update.message.reply_text(escape_markdown_v2("Aviso enviado al inquilino."),
                                            reply_markup=teclado_admin_comunicacion(), parse_mode='MarkdownV2')
        except Exception as e:
            logger.error(f"Error al enviar aviso al inquilino {target_id}: {e}")
            await update.message.reply_text(escape_markdown_v2("Error al enviar aviso al inquilino. Asegúrate de que el Chat ID sea correcto y que el bot haya interactuado con él antes."),
                                            reply_markup=teclado_admin_comunicacion(), parse_mode='MarkdownV2')
    else:
        await update.message.reply_text(escape_markdown_v2("Error: Alcance del aviso no definido. Intenta de nuevo."),
                                        reply_markup=teclado_admin_comunicacion(), parse_mode='MarkdownV2')

    if 'notice_scope' in context.user_data: del context.user_data['notice_scope']
    if 'notice_target_id' in context.user_data: del context.user_data['notice_target_id']

    return ConversationHandler.END

# --- Handlers para modificar inquilino ---

async def handle_admin_modificar_inquilino_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Maneja el click en 'Modificar datos de inquilino' y muestra la lista."""
    query = update.callback_query
    await query.answer()
    cursor.execute("SELECT chat_id, nombre, ci FROM inquilinos")
    inquilinos = cursor.fetchall()
    if not inquilinos:
        await query.edit_message_text(
            escape_markdown_v2("No hay inquilinos para modificar."),
            reply_markup=teclado_admin_inquilinos(), parse_mode='MarkdownV2'
        )
        return ConversationHandler.END
    buttons = [
        [InlineKeyboardButton(escape_markdown_v2(f"{nom} (CI: {ci}) - ID: {cid}"), callback_data=f"modinq_{cid}")]
        for cid, nom, ci in inquilinos
    ]
    buttons.append([InlineKeyboardButton("Volver", callback_data='admin_menu_inquilinos')])
    await query.edit_message_text(
        escape_markdown_v2("Selecciona el inquilino a modificar:"),
        reply_markup=InlineKeyboardMarkup(buttons), parse_mode='MarkdownV2'
    )
    return ADMIN_MODIFICAR_INQUILINO_SELECT

async def admin_modificar_inquilino_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Maneja la selección de inquilino a modificar y pide el campo."""
    query = update.callback_query
    await query.answer()
    chat_id_modificar = int(query.data.split("_")[1])
    context.user_data['mod_inq_chat_id'] = chat_id_modificar
    inquilino_info = obtener_inquilino(chat_id_modificar)
    nombre_inquilino = inquilino_info[1] if inquilino_info else "Desconocido"

    await query.edit_message_text(
        escape_markdown_v2(f"¿Qué dato de {escape_markdown_v2(nombre_inquilino)} (ID: {chat_id_modificar}) deseas modificar?"),
        reply_markup=teclado_modificar_inquilino_campos(), parse_mode='MarkdownV2'
    )
    return ADMIN_MODIFICAR_INQUILINO_FIELD

async def admin_modificar_inquilino_field(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Maneja la selección del campo a modificar y pide el nuevo valor."""
    query = update.callback_query
    await query.answer()
    field_to_modify = query.data.split("_")[2]
    context.user_data['mod_inq_field'] = field_to_modify
    chat_id_modificar = context.user_data.get('mod_inq_chat_id')

    prompt_message = ""
    reply_markup = boton_volver_menu('admin', 'admin_modificar_inquilino')
    if field_to_modify == 'nombre':
        prompt_message = escape_markdown_v2("Ingresa el nuevo nombre completo:")
    elif field_to_modify == 'ci':
        prompt_message = escape_markdown_v2("Ingresa el nuevo número de carnet de identidad:")
    elif field_to_modify == 'fecha_ingreso':
        prompt_message = escape_markdown_v2("Ingresa la nueva fecha de ingreso (YYYY-MM-DD):")
    elif field_to_modify == 'monto_alquiler':
        prompt_message = escape_markdown_v2("Ingresa el nuevo monto de alquiler:")
    elif field_to_modify == 'num_personas':
        prompt_message = escape_markdown_v2("Ingresa el nuevo número de personas:")
    elif field_to_modify == 'tipo_alquiler':
        prompt_message = escape_markdown_v2("Selecciona el nuevo tipo de alquiler:")
        reply_markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("Todo incluido", callback_data='mod_val_tipo_todo')],
            [InlineKeyboardButton("Prorrateo servicios", callback_data='mod_val_tipo_prorrateo')],
        ])
    elif field_to_modify == 'propiedad_id':
        propiedades = obtener_propiedades()
        if not propiedades:
            await query.edit_message_text(escape_markdown_v2("No hay propiedades para asignar. Asigna una propiedad primero."), reply_markup=boton_volver_menu('admin', 'admin_modificar_inquilino'), parse_mode='MarkdownV2')
            return ADMIN_MODIFICAR_INQUILINO_FIELD
        buttons = [[InlineKeyboardButton(escape_markdown_v2(p[1]), callback_data=f"mod_val_prop_{p[0]}")] for p in propiedades]
        buttons.append([InlineKeyboardButton("Ninguna", callback_data='mod_val_prop_none')])
        prompt_message = escape_markdown_v2("Selecciona la nueva propiedad:")
        reply_markup = InlineKeyboardMarkup(buttons)
    elif field_to_modify in ['medidor_luz_id', 'medidor_agua_id', 'medidor_gas_id']:
        tipo_servicio = field_to_modify.replace('medidor_', '').replace('_id', '')
        inquilino = obtener_inquilino(chat_id_modificar)
        propiedad_id = inquilino[7]
        if not propiedad_id:
            await query.edit_message_text(escape_markdown_v2("El inquilino no tiene una propiedad asignada. Asigna una propiedad primero."), reply_markup=boton_volver_menu('admin', 'admin_modificar_inquilino'), parse_mode='MarkdownV2')
            return ADMIN_MODIFICAR_INQUILINO_FIELD
        medidores = obtener_medidores_por_propiedad(propiedad_id, tipo_servicio)
        if not medidores:
            await query.edit_message_text(escape_markdown_v2(f"No hay medidores de {escape_markdown_v2(tipo_servicio.capitalize())} para la propiedad de este inquilino."), reply_markup=boton_volver_menu('admin', 'admin_modificar_inquilino'), parse_mode='MarkdownV2')
            return ADMIN_MODIFICAR_INQUILINO_FIELD
        buttons = [[InlineKeyboardButton(escape_markdown_v2(m[1]), callback_data=f"mod_val_med_{m[0]}")] for m in medidores]
        buttons.append([InlineKeyboardButton("Ninguno", callback_data='mod_val_med_none')])
        prompt_message = escape_markdown_v2(f"Selecciona el nuevo medidor de {escape_markdown_v2(tipo_servicio.capitalize())}:")
        reply_markup = InlineKeyboardMarkup(buttons)
    else:
        await query.edit_message_text(escape_markdown_v2("Campo no reconocido para modificar."), reply_markup=teclado_admin_inquilinos(), parse_mode='MarkdownV2')
        return ConversationHandler.END

    await query.edit_message_text(prompt_message, reply_markup=reply_markup, parse_mode='MarkdownV2')
    return ADMIN_MODIFICAR_INQUILINO_VALUE

async def admin_modificar_inquilino_value(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Recibe el nuevo valor y actualiza el dato del inquilino."""
    message_editor = update.message.reply_text if update.message else update.callback_query.edit_message_text
    if update.callback_query: await update.callback_query.answer()

    chat_id_modificar = context.user_data.get('mod_inq_chat_id')
    field_to_modify = context.user_data.get('mod_inq_field')
    new_value = None
    update_success = False
    message_text = escape_markdown_v2("Dato actualizado correctamente.")

    if update.message and update.message.text:
        new_value_str = update.message.text.strip()
    elif update.callback_query:
        new_value_str = update.callback_query.data.split("_")[-1]
    else:
        await message_editor(
            escape_markdown_v2("Entrada inválida. Por favor, intenta de nuevo."),
            reply_markup=boton_volver_menu('admin', 'admin_modificar_inquilino'), parse_mode='MarkdownV2'
        )
        return ADMIN_MODIFICAR_INQUILINO_VALUE

    try:
        if field_to_modify in ['nombre', 'ci']:
            new_value = new_value_str
        elif field_to_modify == 'fecha_ingreso':
            datetime.strptime(new_value_str, '%Y-%m-%d')
            new_value = new_value_str
        elif field_to_modify == 'monto_alquiler':
            new_value = float(new_value_str)
            if new_value <= 0: raise ValueError("El monto debe ser positivo.")
        elif field_to_modify == 'num_personas':
            new_value = int(new_value_str)
            if new_value <= 0: raise ValueError("El número de personas debe ser positivo.")
        elif field_to_modify == 'tipo_alquiler':
            new_value = new_value_str
        elif field_to_modify == 'propiedad_id':
            new_value = int(new_value_str) if new_value_str != 'none' else None
        elif field_to_modify in ['medidor_luz_id', 'medidor_agua_id', 'medidor_gas_id']:
            new_value = int(new_value_str) if new_value_str != 'none' else None
        else:
            message_text = escape_markdown_v2("Campo de modificación no reconocido.")
            update_success = False

        if new_value is not None or (field_to_modify == 'propiedad_id' and new_value_str == 'none') or (field_to_modify in ['medidor_luz_id', 'medidor_agua_id', 'medidor_gas_id'] and new_value_str == 'none'):
            actualizar_datos_inquilino(chat_id_modificar, **{field_to_modify: new_value})
            update_success = True
        else:
            message_text = escape_markdown_v2("Valor inválido o no se pudo procesar.")

    except ValueError as e:
        message_text = escape_markdown_v2(f"Valor ingresado inválido para este campo: {str(e)}. Intenta de nuevo.")
        update_success = False
    except Exception as e:
        logger.error(f"Error al modificar inquilino {chat_id_modificar}, campo {field_to_modify}: {e}")
        message_text = escape_markdown_v2(f"Ocurrió un error al intentar modificar el dato: {str(e)}")
        update_success = False

    if update_success:
        await message_editor(
            message_text,
            reply_markup=teclado_admin_inquilinos(), parse_mode='MarkdownV2'
        )
        return ConversationHandler.END
    else:
        await message_editor(
            message_text,
            reply_markup=boton_volver_menu('admin', 'admin_modificar_inquilino'), parse_mode='MarkdownV2'
        )
        return ADMIN_MODIFICAR_INQUILINO_VALUE

# --- Handlers para modificar propiedades ---

async def handle_admin_modificar_propiedad_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Maneja el click en 'Modificar propiedad' y muestra la lista."""
    query = update.callback_query
    await query.answer()
    propiedades = obtener_propiedades()
    if not propiedades:
        await query.edit_message_text(
            escape_markdown_v2("No hay propiedades para modificar."),
            reply_markup=teclado_gestionar_propiedades(), parse_mode='MarkdownV2'
        )
        return ConversationHandler.END
    buttons = [
        [InlineKeyboardButton(escape_markdown_v2(p[1]), callback_data=f"modprop_{p[0]}")]
        for p in propiedades
    ]
    buttons.append([InlineKeyboardButton("Volver", callback_data='admin_gestionar_propiedades')])
    await query.edit_message_text(
        escape_markdown_v2("Selecciona la propiedad a modificar:"),
        reply_markup=InlineKeyboardMarkup(buttons), parse_mode='MarkdownV2'
    )
    return ADMIN_MODIFICAR_PROPIEDAD_SELECT

async def admin_modificar_propiedad_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Maneja la selección de propiedad a modificar y pide el campo."""
    query = update.callback_query
    await query.answer()
    propiedad_id_modificar = int(query.data.split("_")[1])
    context.user_data['mod_prop_id'] = propiedad_id_modificar
    propiedad_info = obtener_propiedad_por_id(propiedad_id_modificar)
    nombre_propiedad = propiedad_info[1] if propiedad_info else "Desconocida"

    keyboard = [
        [InlineKeyboardButton("Nombre", callback_data='mod_prop_nombre')],
        [InlineKeyboardButton("Dirección", callback_data='mod_prop_direccion')],
        [InlineKeyboardButton("SSID Wi-Fi", callback_data='mod_prop_wifi_ssid')],
        [InlineKeyboardButton("Contraseña Wi-Fi", callback_data='mod_prop_wifi_password')],
        [InlineKeyboardButton("Volver a Gestión de Propiedades", callback_data='admin_gestionar_propiedades')],
    ]
    await query.edit_message_text(
        escape_markdown_v2(f"¿Qué dato de la propiedad '{escape_markdown_v2(nombre_propiedad)}' deseas modificar?"),
        reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='MarkdownV2'
    )
    return ADMIN_MODIFICAR_PROPIEDAD_FIELD

async def admin_modificar_propiedad_field(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Maneja la selección del campo a modificar de la propiedad y pide el nuevo valor."""
    query = update.callback_query
    await query.answer()
    field_to_modify = query.data.split("_")[2]
    context.user_data['mod_prop_field'] = field_to_modify

    prompt_message = ""
    if field_to_modify == 'nombre':
        prompt_message = escape_markdown_v2("Ingresa el nuevo nombre de la propiedad:")
    elif field_to_modify == 'direccion':
        prompt_message = escape_markdown_v2("Ingresa la nueva dirección de la propiedad:")
    elif field_to_modify == 'wifi_ssid':
        prompt_message = escape_markdown_v2("Ingresa el nuevo SSID de Wi-Fi (o 'N/A' si no aplica):")
    elif field_to_modify == 'wifi_password':
        prompt_message = escape_markdown_v2("Ingresa la nueva contraseña de Wi-Fi (o 'N/A' si no aplica):")
    else:
        await query.edit_message_text(escape_markdown_v2("Campo no reconocido para modificar propiedad."), reply_markup=teclado_gestionar_propiedades(), parse_mode='MarkdownV2')
        return ConversationHandler.END

    await query.edit_message_text(prompt_message, reply_markup=boton_volver_menu('admin', 'admin_propiedades'), parse_mode='MarkdownV2')
    return ADMIN_MODIFICAR_PROPIEDAD_VALUE

async def admin_modificar_propiedad_value(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Recibe el nuevo valor y actualiza el dato de la propiedad."""
    message_editor = update.message.reply_text if update.message else update.callback_query.edit_message_text
    if update.callback_query: await update.callback_query.answer()

    propiedad_id_modificar = context.user_data.get('mod_prop_id')
    field_to_modify = context.user_data.get('mod_prop_field')
    new_value = None
    update_success = False
    message_text = escape_markdown_v2("Dato de propiedad actualizado correctamente.")

    if update.message and update.message.text:
        new_value_str = update.message.text.strip()
    else:
        await message_editor(
            escape_markdown_v2("Entrada inválida. Por favor, intenta de nuevo."),
            reply_markup=boton_volver_menu('admin', 'admin_propiedades'), parse_mode='MarkdownV2'
        )
        return ADMIN_MODIFICAR_PROPIEDAD_VALUE

    try:
        if field_to_modify in ['nombre', 'direccion']:
            new_value = new_value_str
        elif field_to_modify in ['wifi_ssid', 'wifi_password']:
            new_value = new_value_str if new_value_str.upper() != 'N/A' else None
        else:
            message_text = escape_markdown_v2("Campo de modificación no reconocido.")
            update_success = False

        if new_value is not None or new_value_str.upper() == 'N/A':
            actualizar_datos_propiedad(propiedad_id_modificar, **{field_to_modify: new_value})
            update_success = True
        else:
            message_text = escape_markdown_v2("Valor inválido o no se pudo procesar.")

    except Exception as e:
        logger.error(f"Error al modificar propiedad {propiedad_id_modificar}, campo {field_to_modify}: {e}")
        message_text = escape_markdown_v2(f"Ocurrió un error al intentar modificar el dato: {str(e)}")
        update_success = False

    if update_success:
        await message_editor(
            message_text,
            reply_markup=teclado_gestionar_propiedades(), parse_mode='MarkdownV2'
        )
        return ConversationHandler.END
    else:
        await message_editor(
            message_text,
            reply_markup=boton_volver_menu('admin', 'admin_propiedades'), parse_mode='MarkdownV2'
        )
        return ADMIN_MODIFICAR_PROPIEDAD_VALUE


# --- Handlers para generar cobro mensual (NUEVOS) ---

async def handle_admin_generar_cobro_mensual_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Maneja el click en 'Generar Cobro Mensual' y pide el alcance."""
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        escape_markdown_v2("¿Para quién deseas generar el cobro mensual?"),
        reply_markup=teclado_generar_cobro_mensual_scope(), parse_mode='MarkdownV2'
    )
    return ADMIN_GENERAR_COBRO_MENSUAL_SCOPE

async def admin_generar_cobro_mensual_scope(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Maneja la selección del alcance del cobro mensual (todos o por propiedad)."""
    query = update.callback_query
    await query.answer()
    scope = query.data.split("_")[2]
    context.user_data['charge_scope'] = scope

    if scope == 'all':
        await query.edit_message_text(
            escape_markdown_v2("¿Estás seguro de que deseas generar el cobro mensual para *todos* los inquilinos registrados?"),
            parse_mode='MarkdownV2',
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Sí, generar para todos", callback_data='charge_confirm_all')],
                [InlineKeyboardButton("No, cancelar", callback_data='charge_cancel')]
            ])
        )
        return ADMIN_GENERAR_COBRO_MENSUAL_CONFIRM
    elif scope == 'property':
        propiedades = obtener_propiedades()
        if not propiedades:
            await query.edit_message_text(escape_markdown_v2("No hay propiedades registradas para generar cobros. Por favor, registra una propiedad primero."),
                                          reply_markup=teclado_admin_comunicacion(), parse_mode='MarkdownV2')
            return ConversationHandler.END
        buttons = [[InlineKeyboardButton(escape_markdown_v2(p[1]), callback_data=f"chargeprop_{p[0]}")] for p in propiedades]
        buttons.append([InlineKeyboardButton("Volver", callback_data='admin_menu_comunicacion')])
        await query.edit_message_text(escape_markdown_v2("Selecciona la propiedad para la cual generar el cobro:"),
                                      reply_markup=InlineKeyboardMarkup(buttons), parse_mode='MarkdownV2')
        return ADMIN_GENERAR_COBRO_MENSUAL_PROPERTY_SELECT
    else:
        await query.edit_message_text(escape_markdown_v2("Opción inválida. Intenta de nuevo."), reply_markup=teclado_generar_cobro_mensual_scope(), parse_mode='MarkdownV2')
        return ADMIN_GENERAR_COBRO_MENSUAL_SCOPE

async def admin_generar_cobro_mensual_property_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Maneja la selección de propiedad para generar cobro mensual."""
    query = update.callback_query
    await query.answer()
    propiedad_id = int(query.data.split("_")[1])
    context.user_data['charge_target_id'] = propiedad_id
    propiedad_info = obtener_propiedad_por_id(propiedad_id)
    nombre_propiedad = propiedad_info[1] if propiedad_info else "Desconocida"

    await query.edit_message_text(
        escape_markdown_v2(f"¿Estás seguro de que deseas generar el cobro mensual para los inquilinos de '{escape_markdown_v2(nombre_propiedad)}'?"),
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("Sí, generar para esta propiedad", callback_data='charge_confirm_property')],
            [InlineKeyboardButton("No, cancelar", callback_data='charge_cancel')]
        ]),
        parse_mode='MarkdownV2'
    )
    return ADMIN_GENERAR_COBRO_MENSUAL_CONFIRM

async def admin_generar_cobro_mensual_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Confirma y ejecuta la generación del cobro mensual."""
    query = update.callback_query
    await query.answer()
    scope = context.user_data.get('charge_scope')
    target_id = context.user_data.get('charge_target_id')
    
    current_year = datetime.now().year
    current_month = datetime.now().month

    if query.data == 'charge_cancel':
        await query.edit_message_text(escape_markdown_v2("Generación de cobro mensual cancelada."), reply_markup=teclado_admin_comunicacion(), parse_mode='MarkdownV2')
        return ConversationHandler.END

    inquilinos_a_cobrar = []
    if scope == 'all':
        cursor.execute("SELECT chat_id, nombre, num_personas, propiedad_id, monto_alquiler, tipo_alquiler, medidor_asignado_luz_id, medidor_asignado_agua_id, medidor_asignado_gas_id, saldo FROM inquilinos WHERE fecha_ingreso IS NOT NULL") # Solo inquilinos con registro completo
        inquilinos_a_cobrar = cursor.fetchall()
    elif scope == 'property' and target_id:
        cursor.execute("SELECT chat_id, nombre, num_personas, propiedad_id, monto_alquiler, tipo_alquiler, medidor_asignado_luz_id, medidor_asignado_agua_id, medidor_asignado_gas_id, saldo FROM inquilinos WHERE propiedad_id = ? AND fecha_ingreso IS NOT NULL", (target_id,)) # Solo inquilinos con registro completo
        inquilinos_a_cobrar = cursor.fetchall()
    
    if not inquilinos_a_cobrar:
        await query.edit_message_text(escape_markdown_v2("No se encontraron inquilinos con registro completo para generar el cobro en el alcance seleccionado."), reply_markup=teclado_admin_comunicacion(), parse_mode='MarkdownV2')
        return ConversationHandler.END

    cobros_generados = 0
    for inquilino_data in inquilinos_a_cobrar:
        chat_id = inquilino_data[0]
        nombre_inquilino = inquilino_data[1]
        num_personas_inquilino = inquilino_data[2] if inquilino_data[2] is not None else 1
        propiedad_id = inquilino_data[3]
        monto_alquiler = inquilino_data[4] if inquilino_data[4] is not None else 0.0
        tipo_alquiler = inquilino_data[5]
        medidor_luz_individual_id = inquilino_data[6]
        medidor_agua_main_id = inquilino_data[7]
        medidor_gas_main_id = inquilino_data[8]
        saldo_actual = inquilino_data[9] if inquilino_data[9] is not None else 0.0
        
        total_a_cobrar = monto_alquiler
        detalle_cobro = f"Cobro mensual para {escape_markdown_v2(nombre_inquilino)} (ID: {chat_id}):\n\n"
        detalle_cobro += f"- Alquiler base: {monto_alquiler:.2f} Bs.\n"

        if tipo_alquiler == 'prorrateo':
            detalle_cobro += "\n*Detalle de Servicios (Mes anterior):*\n"
            total_servicios_prorrateo = 0.0

            # Prorrateo de Luz (kWh-based if individual meter, else included)
            if medidor_luz_individual_id:
                current_reading = obtener_ultima_lectura(medidor_luz_individual_id)
                previous_reading = obtener_lectura_anterior_mes(medidor_luz_individual_id, current_year, current_month)
                tenant_kwh_consumed = current_reading - previous_reading

                cursor.execute("SELECT id FROM medidores WHERE propiedad_id = ? AND tipo_servicio = 'luz' LIMIT 1", (propiedad_id,))
                main_luz_medidor_info = cursor.fetchone()
                
                costo_inquilino_luz = 0.0
                if main_luz_medidor_info:
                    main_luz_medidor_id = main_luz_medidor_info[0]
                    main_luz_bill, main_luz_kwh_total = obtener_facturas_por_medidor_y_mes(main_luz_medidor_id, current_year, current_month)

                    if main_luz_kwh_total > 0:
                        cost_per_kwh = main_luz_bill / main_luz_kwh_total
                        costo_inquilino_luz = cost_per_kwh * tenant_kwh_consumed
                        detalle_cobro += f"  - Luz (Consumo: {tenant_kwh_consumed:.2f} kWh): {costo_inquilino_luz:.2f} Bs. (Tarifa: {cost_per_kwh:.2f} Bs/kWh)\n"
                    else:
                        detalle_cobro += f"  - Luz: No se pudo calcular (kWh total de factura principal 0 o no disponible para medidor {main_luz_medidor_id}).\n"
                else:
                    detalle_cobro += f"  - Luz: No se encontró medidor principal de luz para la propiedad {propiedad_id}.\n"
                total_servicios_prorrateo += costo_inquilino_luz
            else:
                detalle_cobro += "  - Luz: Incluida en alquiler base (sin medidor individual asignado).\n"

            # Prorrateo de Agua (people-based)
            if medidor_agua_main_id:
                medidor_info = obtener_medidor_por_id(medidor_agua_main_id)
                if medidor_info:
                    cursor.execute("SELECT SUM(num_personas) FROM inquilinos WHERE medidor_asignado_agua_id = ?", (medidor_agua_main_id,))
                    total_personas_medidor_agua = cursor.fetchone()[0] or 1

                    main_agua_bill, _ = obtener_facturas_por_medidor_y_mes(medidor_agua_main_id, current_year, current_month)
                    costo_por_persona_agua = (main_agua_bill / total_personas_medidor_agua) if total_personas_medidor_agua > 0 else 0
                    costo_inquilino_agua = costo_por_persona_agua * num_personas_inquilino
                    total_servicios_prorrateo += costo_inquilino_agua
                    detalle_cobro += f"  - Agua ({escape_markdown_v2(medidor_info[2])}): {costo_inquilino_agua:.2f} Bs. (Total medidor: {main_agua_bill:.2f} Bs. / {total_personas_medidor_agua} pers.)\n"
            else:
                detalle_cobro += "  - Agua: Incluida en alquiler base (sin medidor principal asignado).\n"

            # Prorrateo de Gas (people-based)
            if medidor_gas_main_id:
                medidor_info = obtener_medidor_por_id(inquilino_data[10])
                if medidor_info:
                    cursor.execute("SELECT SUM(num_personas) FROM inquilinos WHERE medidor_asignado_gas_id = ?", (medidor_gas_main_id,))
                    total_personas_medidor_gas = cursor.fetchone()[0] or 1

                    main_gas_bill, _ = obtener_facturas_por_medidor_y_mes(medidor_gas_main_id, current_year, current_month)
                    costo_por_persona_gas = (main_gas_bill / total_personas_medidor_gas) if total_personas_medidor_gas > 0 else 0
                    costo_inquilino_gas = costo_por_persona_gas * num_personas_inquilino
                    total_servicios_prorrateo += costo_inquilino_gas
                    detalle_cobro += f"  - Gas ({escape_markdown_v2(medidor_info[2])}): {costo_inquilino_gas:.2f} Bs. (Total medidor: {main_gas_bill:.2f} Bs. / {total_personas_medidor_gas} pers.)\n"
            else:
                detalle_cobro += "  - Gas: Incluida en alquiler base (sin medidor principal asignado).\n"

            # Prorrateo de Internet/TV (people-based, for the property)
            cursor.execute("SELECT id FROM medidores WHERE propiedad_id = ? AND tipo_servicio = 'internet_tv' LIMIT 1", (propiedad_id,))
            main_internet_tv_medidor_info = cursor.fetchone()
            
            costo_inquilino_internet_tv = 0.0
            if main_internet_tv_medidor_info:
                main_internet_tv_medidor_id = main_internet_tv_medidor_info[0]
                main_internet_tv_bill, _ = obtener_facturas_por_medidor_y_mes(main_internet_tv_medidor_id, current_year, current_month)
                
                cursor.execute("SELECT SUM(num_personas) FROM inquilinos WHERE propiedad_id = ?", (propiedad_id,))
                total_personas_propiedad = cursor.fetchone()[0] or 1

                costo_por_persona_internet_tv = (main_internet_tv_bill / total_personas_propiedad) if total_personas_propiedad > 0 else 0
                costo_inquilino_internet_tv = costo_por_persona_internet_tv * num_personas_inquilino
                total_servicios_prorrateo += costo_inquilino_internet_tv
                detalle_cobro += f"  - Internet/TV: {costo_inquilino_internet_tv:.2f} Bs. (Total propiedad: {main_internet_tv_bill:.2f} Bs. / {total_personas_propiedad} pers.)\n"
            else:
                detalle_cobro += "  - Internet/TV: No se encontró medidor principal de Internet/TV para la propiedad o no aplica.\n"
            
            total_a_cobrar += total_servicios_prorrateo
            detalle_cobro += f"\nTotal servicios: {total_servicios_prorrateo:.2f} Bs.\n"

        detalle_cobro += f"\n*Total a cobrar este mes: {total_a_cobrar:.2f} Bs.*"
        
        # Actualizar el saldo del inquilino
        nuevo_saldo = saldo_actual + total_a_cobrar
        actualizar_datos_inquilino(chat_id, saldo=nuevo_saldo)
        
        detalle_cobro += f"\nTu nuevo saldo pendiente es: {nuevo_saldo:.2f} Bs."

        try:
            await context.bot.send_message(
                chat_id=chat_id,
                text=escape_markdown_v2(detalle_cobro),
                parse_mode='MarkdownV2'
            )
            cobros_generados += 1
            logger.info(f"Cobro mensual generado y enviado a {escape_markdown_v2(nombre_inquilino)} ({chat_id}).")
        except Exception as e:
            logger.error(f"Error al enviar cobro mensual a {escape_markdown_v2(nombre_inquilino)} ({chat_id}): {e}")
    
    await query.edit_message_text(escape_markdown_v2(f"Cobro mensual generado para {cobros_generados} inquilino(s)."), reply_markup=teclado_admin_comunicacion(), parse_mode='MarkdownV2')
    return ConversationHandler.END

# --- Handlers para inquilinos ---

async def ver_mi_propiedad(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Muestra los detalles de la propiedad asignada al inquilino."""
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat.id
    inquilino = obtener_inquilino(chat_id)

    if not inquilino or inquilino[7] is None: # inquilino[7] es propiedad_id
        await query.edit_message_text(escape_markdown_v2("No tienes una propiedad asignada aún. Contacta al administrador."),
                                      reply_markup=boton_volver_menu('inquilino'), parse_mode='MarkdownV2')
        return ConversationHandler.END

    propiedad_id = inquilino[7]
    propiedad = obtener_propiedad_por_id(propiedad_id)

    if propiedad:
        texto = (
            f"🏡 *Detalles de tu Propiedad* 🏡\n\n"
            f"*Nombre:* {escape_markdown_v2(propiedad[1])}\n"
            f"*Dirección:* {escape_markdown_v2(propiedad[2])}\n\n"
            f"🌐 *Información Wi-Fi:*\n"
            f"  - *SSID:* `{escape_markdown_v2(propiedad[3] if propiedad[3] else 'No asignado')}`\n"
            f"  - *Contraseña:* `{escape_markdown_v2(propiedad[4] if propiedad[4] else 'No asignado')}`\n"
        )
        
        has_medidores = False
        medidor_luz = obtener_medidor_por_id(inquilino[8]) if inquilino[8] else None
        medidor_agua = obtener_medidor_por_id(inquilino[9]) if inquilino[9] else None
        medidor_gas = obtener_medidor_por_id(inquilino[10]) if inquilino[10] else None

        if medidor_luz or medidor_agua or medidor_gas:
            texto += "\n⚡💧🔥 *Tus Medidores Asignados:*\n"
            has_medidores = True

        if medidor_luz:
            texto += f"  - *Luz:* {escape_markdown_v2(medidor_luz[2])} (Tipo: {escape_markdown_v2(medidor_luz[3].capitalize())})\n"
        if medidor_agua:
            texto += f"  - *Agua:* {escape_markdown_v2(medidor_agua[2])} (Tipo: {escape_markdown_v2(medidor_agua[3].capitalize())})\n"
        if medidor_gas:
            texto += f"  - *Gas:* {escape_markdown_v2(medidor_gas[2])} (Tipo: {escape_markdown_v2(medidor_gas[3].capitalize())})\n"

        if not has_medidores:
            texto += "\n_No tienes medidores de servicios asignados a tu propiedad._\n"

        await query.edit_message_text(escape_markdown_v2(texto), reply_markup=boton_volver_menu('inquilino'), parse_mode='MarkdownV2')
    else:
        await query.edit_message_text(escape_markdown_v2("No se encontró la información de tu propiedad. Contacta al administrador."),
                                      reply_markup=boton_volver_menu('inquilino'), parse_mode='MarkdownV2')
    return ConversationHandler.END

async def ver_saldo_y_pagos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Muestra el saldo actual del inquilino y el detalle de pagos/prorrateo."""
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat.id
    inquilino = obtener_inquilino(chat_id)

    if not inquilino:
        await query.edit_message_text(escape_markdown_v2("No estás registrado. Por favor, usa /start para iniciar el registro."),
                                      reply_markup=boton_volver_menu('inquilino'), parse_mode='MarkdownV2')
        return ConversationHandler.END
    
    if inquilino[3] is None: # Si el inquilino no tiene fecha de ingreso, su registro está incompleto
        await query.edit_message_text(
            escape_markdown_v2("Tu registro está pendiente de validación por el administrador. Por favor, espera a que el administrador complete tu registro para ver esta información."),
            reply_markup=boton_volver_menu('inquilino'), parse_mode='MarkdownV2'
        )
        return ConversationHandler.END


    # Datos del inquilino:
    # 0: chat_id, 1: nombre, 2: ci, 3: fecha_ingreso, 4: monto_alquiler, 5: tipo_alquiler, 6: saldo
    # 7: propiedad_id, 8: medidor_luz_id, 9: medidor_agua_id, 10: medidor_gas_id, 11: num_personas
    nombre_inquilino = inquilino[1]
    monto_alquiler = inquilino[4] if inquilino[4] is not None else 0.0
    saldo_actual = inquilino[6] if inquilino[6] is not None else 0.0
    tipo_alquiler = inquilino[5]
    propiedad_id = inquilino[7]
    num_personas_inquilino = inquilino[11] if inquilino[11] is not None else 1

    texto = f"Hola {escape_markdown_v2(nombre_inquilino)},\n\n"
    texto += f"Tu alquiler mensual base es: *{monto_alquiler:.2f} Bs.*"
    texto += f"\nSaldo pendiente total: *{saldo_actual:.2f} Bs.*"
    texto += "\n\n"

    # Calcular prorrateo si aplica (solo para mostrar un estimado, no afecta el saldo directamente aquí)
    if tipo_alquiler == 'prorrateo':
        texto += "*Estimado de Servicios (Mes actual):*\n"
        total_servicios_prorrateo_estimado = 0.0
        current_year = datetime.now().year
        current_month = datetime.now().month

        # Prorrateo de Luz (kWh-based if individual meter, else included)
        medidor_luz_individual_id = inquilino[8]
        if medidor_luz_individual_id:
            current_reading = obtener_ultima_lectura(medidor_luz_individual_id)
            previous_reading = obtener_lectura_anterior_mes(medidor_luz_individual_id, current_year, current_month)
            tenant_kwh_consumed = current_reading - previous_reading

            cursor.execute("SELECT id FROM medidores WHERE propiedad_id = ? AND tipo_servicio = 'luz' LIMIT 1", (propiedad_id,))
            main_luz_medidor_info = cursor.fetchone()
            
            costo_inquilino_luz = 0.0
            if main_luz_medidor_info:
                main_luz_medidor_id = main_luz_medidor_info[0]
                main_luz_bill, main_luz_kwh_total = obtener_facturas_por_medidor_y_mes(main_luz_medidor_id, current_year, current_month)

                if main_luz_kwh_total > 0:
                    cost_per_kwh = main_luz_bill / main_luz_kwh_total
                    costo_inquilino_luz = cost_per_kwh * tenant_kwh_consumed
                    texto += f"  - Luz (Consumo: {tenant_kwh_consumed:.2f} kWh): {costo_inquilino_luz:.2f} Bs. (Tarifa: {cost_per_kwh:.2f} Bs/kWh)\n"
                else:
                    texto += f"  - Luz: No se pudo calcular (kWh total de factura principal 0 o no disponible).\n"
            else:
                texto += f"  - Luz: No se encontró medidor principal de luz para la propiedad.\n"
            total_servicios_prorrateo_estimado += costo_inquilino_luz
        else:
            texto += "  - Luz: Incluida en alquiler base (sin medidor individual asignado).\n"

        # Prorrateo de Agua (people-based)
        medidor_agua_main_id = inquilino[9]
        if medidor_agua_main_id:
            medidor_info = obtener_medidor_por_id(medidor_agua_main_id)
            if medidor_info:
                cursor.execute("SELECT SUM(num_personas) FROM inquilinos WHERE medidor_asignado_agua_id = ?", (medidor_agua_main_id,))
                total_personas_medidor_agua = cursor.fetchone()[0] or 1

                main_agua_bill, _ = obtener_facturas_por_medidor_y_mes(medidor_agua_main_id, current_year, current_month)
                costo_por_persona_agua = (main_agua_bill / total_personas_medidor_agua) if total_personas_medidor_agua > 0 else 0
                costo_inquilino_agua = costo_por_persona_agua * num_personas_inquilino
                total_servicios_prorrateo_estimado += costo_inquilino_agua
                texto += f"  - Agua ({escape_markdown_v2(medidor_info[2])}): {costo_inquilino_agua:.2f} Bs. (Total medidor: {main_agua_bill:.2f} Bs. / {total_personas_medidor_agua} pers.)\n"
        else:
            texto += "  - Agua: Incluida en alquiler base (sin medidor principal asignado).\n"

        # Prorrateo de Gas (people-based)
        medidor_gas_main_id = inquilino[10]
        if medidor_gas_main_id:
            medidor_info = obtener_medidor_por_id(inquilino[10])
            if medidor_info:
                cursor.execute("SELECT SUM(num_personas) FROM inquilinos WHERE medidor_asignado_gas_id = ?", (medidor_gas_main_id,))
                total_personas_medidor_gas = cursor.fetchone()[0] or 1

                main_gas_bill, _ = obtener_facturas_por_medidor_y_mes(medidor_gas_main_id, current_year, current_month)
                costo_por_persona_gas = (main_gas_bill / total_personas_medidor_gas) if total_personas_medidor_gas > 0 else 0
                costo_inquilino_gas = costo_por_persona_gas * num_personas_inquilino
                total_servicios_prorrateo_estimado += costo_inquilino_gas
                texto += f"  - Gas ({escape_markdown_v2(medidor_info[2])}): {costo_inquilino_gas:.2f} Bs. (Total medidor: {main_gas_bill:.2f} Bs. / {total_personas_medidor_gas} pers.)\n"
        else:
            texto += "  - Gas: Incluida en alquiler base (sin medidor principal asignado).\n"

        # Prorrateo de Internet/TV (people-based, for the property)
        cursor.execute("SELECT id FROM medidores WHERE propiedad_id = ? AND tipo_servicio = 'internet_tv' LIMIT 1", (propiedad_id,))
        main_internet_tv_medidor_info = cursor.fetchone()
        
        costo_inquilino_internet_tv = 0.0
        if main_internet_tv_medidor_info:
            main_internet_tv_medidor_id = main_internet_tv_medidor_info[0]
            main_internet_tv_bill, _ = obtener_facturas_por_medidor_y_mes(main_internet_tv_medidor_id, current_year, current_month)
            
            cursor.execute("SELECT SUM(num_personas) FROM inquilinos WHERE propiedad_id = ?", (propiedad_id,))
            total_personas_propiedad = cursor.fetchone()[0] or 1

            costo_por_persona_internet_tv = (main_internet_tv_bill / total_personas_propiedad) if total_personas_propiedad > 0 else 0
            costo_inquilino_internet_tv = costo_por_persona_internet_tv * num_personas_inquilino
            total_servicios_prorrateo_estimado += costo_inquilino_internet_tv
            texto += f"  - Internet/TV: {costo_inquilino_internet_tv:.2f} Bs. (Total propiedad: {main_internet_tv_bill:.2f} Bs. / {total_personas_propiedad} pers.)\n"
        else:
            texto += "  - Internet/TV: No se encontró medidor principal de Internet/TV para la propiedad o no aplica.\n"

        texto += f"\nTotal estimado servicios: *{total_servicios_prorrateo_estimado:.2f} Bs.*"
        texto += f"\nTotal mensual estimado (Alquiler + Servicios): *{(monto_alquiler + total_servicios_prorrateo_estimado):.2f} Bs.*"
        texto += "\n\n"

    # Historial de pagos
    cursor.execute("SELECT fecha_pago, monto_pagado, confirmado FROM pagos WHERE chat_id = ? ORDER BY fecha_pago DESC LIMIT 5", (chat_id,))
    pagos_recientes = cursor.fetchall()
    if pagos_recientes:
        texto += "*Últimos pagos registrados:*\n"
        for fecha, monto, confirmado in pagos_recientes:
            estado = "Confirmado" if confirmado else "Pendiente"
            texto += f"- {fecha}: {monto:.2f} Bs. ({estado})\n"
    else:
        texto += "No hay pagos registrados.\n"

    await query.edit_message_text(escape_markdown_v2(texto), reply_markup=boton_volver_menu('inquilino'), parse_mode='MarkdownV2')
    return ConversationHandler.END

async def handle_queja_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Maneja el click en 'Enviar queja/sugerencia'."""
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat.id
    inquilino = obtener_inquilino(chat_id)
    if inquilino and inquilino[3] is not None:
        await query.edit_message_text(
            escape_markdown_v2("Por favor, escribe tu queja o sugerencia:"),
            reply_markup=boton_volver_menu('inquilino'), parse_mode='MarkdownV2'
        )
        return INQ_ENVIAR_QUEJA
    else:
        await query.edit_message_text(
            escape_markdown_v2("No puedes enviar quejas aún. Tu registro está pendiente o incompleto. Contacta al administrador."),
            reply_markup=teclado_inquilino(), parse_mode='MarkdownV2'
        )
        return ConversationHandler.END

async def inq_enviar_queja(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Recibe la queja/sugerencia del inquilino y la registra."""
    chat_id = update.effective_chat.id
    texto_queja = update.message.text.strip()
    if not texto_queja:
        await update.message.reply_text(escape_markdown_v2("La queja no puede estar vacía. Por favor, escribe tu queja o sugerencia:"),
                                        reply_markup=boton_volver_menu('inquilino'), parse_mode='MarkdownV2')
        return INQ_ENVIAR_QUEJA

    # Registrar la queja y obtener su ID
    cursor.execute(
        "INSERT INTO quejas(chat_id, fecha, texto, resuelto) VALUES (?, ?, ?, 0)",
        (chat_id, datetime.now().strftime("%Y-%m-%d %H:%M"), texto_queja)
    )
    conn.commit()
    queja_id = cursor.lastrowid # Obtener el ID de la queja recién insertada
    logger.info(f"Queja registrada de {chat_id}: {texto_queja}. Queja ID: {queja_id}")

    await update.message.reply_text(
        escape_markdown_v2("Gracias, tu queja/sugerencia ha sido enviada a la administración."),
        reply_markup=teclado_inquilino(), parse_mode='MarkdownV2'
    )
    # Notificar al administrador sobre la nueva queja
    for admin_id in ADMIN_IDS:
        try:
            inquilino_info = obtener_inquilino(chat_id)
            inquilino_nombre = inquilino_info[1] if inquilino_info else chat_id
            
            # Botón para marcar como resuelta directamente
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Marcar como Resuelta", callback_data=f"markqueja_{queja_id}")]
            ])

            await context.bot.send_message(
                chat_id=admin_id,
                text=escape_markdown_v2(f"🔔 *Nueva queja/sugerencia de:*\n"
                     f"*Inquilino:* {escape_markdown_v2(inquilino_nombre)} (ID: {chat_id})\n"
                     f"*Mensaje:* {escape_markdown_v2(texto_queja)}\n"
                     f"Usa el menú de administrador para leerla y marcarla como resuelta."),
                reply_markup=keyboard, # Añadir el botón al mensaje
                parse_mode='MarkdownV2'
            )
        except Exception as e:
            logger.error(f"Error al notificar al admin {admin_id} sobre nueva queja: {e}")
    return ConversationHandler.END

async def admin_show_accounting_summary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Muestra un resumen contable del mes actual (pagos confirmados e ingresos)."""
    query = update.callback_query
    await query.answer()

    current_year = datetime.now().year
    current_month = datetime.now().month
    month_name = datetime.now().strftime("%B") # Nombre del mes

    # Ingresos (Pagos Confirmados)
    cursor.execute(
        "SELECT fecha_pago, monto_pagado, chat_id FROM pagos WHERE confirmado = 1 AND strftime('%Y-%m', fecha_pago) = ?",
        (f"{current_year:04d}-{current_month:02d}",)
    )
    ingresos_detalles = cursor.fetchall()
    total_ingresos = sum([row[1] for row in ingresos_detalles])

    # Gastos (Facturas Registradas)
    cursor.execute(
        "SELECT fecha, monto, tipo_servicio, propiedad_id FROM facturas WHERE strftime('%Y-%m', fecha) = ?",
        (f"{current_year:04d}-{current_month:02d}",)
    )
    gastos_detalles = cursor.fetchall()
    total_gastos = sum([row[1] for row in gastos_detalles])

    balance = total_ingresos - total_gastos

    summary_text = (
        f"📊 *Resumen Contable ({escape_markdown_v2(month_name.capitalize())} {current_year})* 📊\n\n"
        f"*Ingresos (Pagos Confirmados):* {total_ingresos:.2f} Bs.\n"
    )
    if ingresos_detalles:
        for fecha, monto, chat_id_inquilino in ingresos_detalles:
            inquilino_info = obtener_inquilino(chat_id_inquilino)
            nombre_inquilino = inquilino_info[1] if inquilino_info else f"ID: {chat_id_inquilino}"
            summary_text += f"  - {fecha}: {monto:.2f} Bs. (de {escape_markdown_v2(nombre_inquilino)})\n"
    else:
        summary_text += "  _No hay ingresos registrados este mes._\n"

    summary_text += f"\n*Gastos (Facturas Registradas):* {total_gastos:.2f} Bs.\n"
    if gastos_detalles:
        for fecha, monto, tipo_servicio, propiedad_id in gastos_detalles:
            propiedad_info = obtener_propiedad_por_id(propiedad_id)
            nombre_propiedad = propiedad_info[1] if propiedad_info else f"ID: {propiedad_id}"
            summary_text += f"  - {fecha}: {monto:.2f} Bs. ({escape_markdown_v2(tipo_servicio.capitalize())} para {escape_markdown_v2(nombre_propiedad)})\n"
    else:
        summary_text += "  _No hay gastos registrados este mes._\n"

    summary_text += f"\n*Balance del Mes:* {balance:.2f} Bs.\n\n"
    summary_text += "Este resumen incluye todos los pagos confirmados y facturas registradas para el mes actual."

    await query.edit_message_text(
        escape_markdown_v2(summary_text),
        reply_markup=boton_volver_menu('admin', 'admin_menu_facturacion'),
        parse_mode='MarkdownV2'
    )
    return ConversationHandler.END


# --- Handlers para mostrar información (sin iniciar conversación) ---

async def menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Maneja las interacciones de los botones inline de los menús que solo muestran información o navegan entre menús."""
    query = update.callback_query
    await query.answer()

    chat_id = query.message.chat.id
    target_menu_data = query.data

    if chat_id in ADMIN_IDS:
        # --- Opciones administrador ---
        if target_menu_data == 'menu_admin':
            await query.edit_message_text(escape_markdown_v2("Panel administrador:"), reply_markup=teclado_admin(), parse_mode='MarkdownV2')
        elif target_menu_data == 'admin_menu_inquilinos':
            await query.edit_message_text(escape_markdown_v2("Menú de Gestión de Inquilinos:"), reply_markup=teclado_admin_inquilinos(), parse_mode='MarkdownV2')
        elif target_menu_data == 'admin_menu_facturacion':
            await query.edit_message_text(escape_markdown_v2("Menú de Facturación y Medidores:"), reply_markup=teclado_admin_facturacion(), parse_mode='MarkdownV2')
        elif target_menu_data == 'admin_menu_comunicacion':
            await query.edit_message_text(escape_markdown_v2("Menú de Comunicación y Pagos:"), reply_markup=teclado_admin_comunicacion(), parse_mode='MarkdownV2')
        elif target_menu_data == 'admin_morosos':
            cursor.execute("SELECT i.nombre, i.ci, i.saldo, p.nombre FROM inquilinos i LEFT JOIN propiedades p ON i.propiedad_id = p.id WHERE i.saldo > 0")
            morosos = cursor.fetchall()
            if not morosos:
                await query.edit_message_text(
                    escape_markdown_v2("No hay inquilinos morosos."),
                    reply_markup=teclado_admin_inquilinos(), parse_mode='MarkdownV2'
                )
            else:
                texto = "Inquilinos morosos:\n\n"
                for nombre, ci, saldo, propiedad_nombre in morosos:
                    prop_info = f" (Propiedad: {escape_markdown_v2(propiedad_nombre)})" if propiedad_nombre else ""
                    texto += f"- {escape_markdown_v2(nombre)} (CI: {escape_markdown_v2(ci)}){prop_info} debe: *{saldo:.2f} Bs.*\n"
                await query.edit_message_text(escape_markdown_v2(texto), reply_markup=teclado_admin_inquilinos(), parse_mode='MarkdownV2')
        elif target_menu_data == 'admin_gestionar_propiedades':
            await query.edit_message_text(escape_markdown_v2("Menú de gestión de propiedades:"), reply_markup=teclado_gestionar_propiedades(), parse_mode='MarkdownV2')
        elif target_menu_data == 'admin_ver_propiedades':
            propiedades = obtener_propiedades()
            if not propiedades:
                await query.edit_message_text(escape_markdown_v2("No hay propiedades registradas."), reply_markup=teclado_gestionar_propiedades(), parse_mode='MarkdownV2')
            else:
                texto = "Propiedades registradas:\n\n"
                for p_id, nombre, direccion, wifi_ssid, wifi_password in propiedades:
                    texto += f"*ID:* {p_id}\n"
                    texto += f"*Nombre:* {escape_markdown_v2(nombre)}\n"
                    texto += f"*Dirección:* {escape_markdown_v2(direccion)}\n"
                    texto += f"  *SSID Wi-Fi:* `{escape_markdown_v2(wifi_ssid if wifi_ssid else 'No asignado')}`\n"
                    texto += f"  *Contraseña Wi-Fi:* `{escape_markdown_v2(wifi_password if wifi_password else 'No asignado')}`\n"
                    medidores = obtener_medidores_por_propiedad(p_id)
                    if medidores:
                        texto += "* Medidores:*\n"
                        for m_id, m_nombre, m_tipo in medidores:
                            texto += f"    - ID: {m_id}, Nombre: {escape_markdown_v2(m_nombre)} (Tipo: {escape_markdown_v2(m_tipo.replace('_', '/').capitalize())})\n"
                    texto += "\n"
                await query.edit_message_text(escape_markdown_v2(texto), reply_markup=teclado_gestionar_propiedades(), parse_mode='MarkdownV2')
        elif target_menu_data == 'admin_resumen_contable':
            current_year = datetime.now().year
            current_month = datetime.now().month
            month_name = datetime.now().strftime("%B")

            cursor.execute(
                "SELECT fecha_pago, monto_pagado, chat_id FROM pagos WHERE confirmado = 1 AND strftime('%Y-%m', fecha_pago) = ?",
                (f"{current_year:04d}-{current_month:02d}",)
            )
            ingresos_detalles = cursor.fetchall()
            total_ingresos = sum([row[1] for row in ingresos_detalles])

            cursor.execute(
                "SELECT fecha, monto, tipo_servicio, propiedad_id FROM facturas WHERE strftime('%Y-%m', fecha) = ?",
                (f"{current_year:04d}-{current_month:02d}",)
            )
            gastos_detalles = cursor.fetchall()
            total_gastos = sum([row[1] for row in gastos_detalles])

            balance = total_ingresos - total_gastos

            summary_text = (
                f"📊 *Resumen Contable ({escape_markdown_v2(month_name.capitalize())} {current_year})* 📊\n\n"
                f"*Ingresos (Pagos Confirmados):* {total_ingresos:.2f} Bs.\n"
            )
            if ingresos_detalles:
                for fecha, monto, chat_id_inquilino in ingresos_detalles:
                    inquilino_info = obtener_inquilino(chat_id_inquilino)
                    nombre_inquilino = inquilino_info[1] if inquilino_info else f"ID: {chat_id_inquilino}"
                    summary_text += f"  - {fecha}: {monto:.2f} Bs. (de {escape_markdown_v2(nombre_inquilino)})\n"
            else:
                summary_text += "  _No hay ingresos registrados este mes._\n"

            summary_text += f"\n*Gastos (Facturas Registradas):* {total_gastos:.2f} Bs.\n"
            if gastos_detalles:
                for fecha, monto, tipo_servicio, propiedad_id in gastos_detalles:
                    propiedad_info = obtener_propiedad_por_id(propiedad_id)
                    nombre_propiedad = propiedad_info[1] if propiedad_info else f"ID: {propiedad_id}"
                    summary_text += f"  - {fecha}: {monto:.2f} Bs. ({escape_markdown_v2(tipo_servicio.capitalize())} para {escape_markdown_v2(nombre_propiedad)})\n"
            else:
                summary_text += "  _No hay gastos registrados este mes._\n"

            summary_text += f"\n*Balance del Mes:* {balance:.2f} Bs.\n\n"
            summary_text += "Este resumen incluye todos los pagos confirmados y facturas registradas para el mes actual."

            await query.edit_message_text(
                escape_markdown_v2(summary_text),
                reply_markup=teclado_admin_facturacion(),
                parse_mode='MarkdownV2'
            )
        elif target_menu_data == 'admin_modificar_inquilino': # Handle the return to modify inquilino menu
            cursor.execute("SELECT chat_id, nombre, ci FROM inquilinos")
            inquilinos = cursor.fetchall()
            if not inquilinos:
                await query.edit_message_text(
                    escape_markdown_v2("No hay inquilinos para modificar."),
                    reply_markup=teclado_admin_inquilinos(), parse_mode='MarkdownV2'
                )
            else:
                buttons = [
                    [InlineKeyboardButton(escape_markdown_v2(f"{nom} (CI: {ci}) - ID: {cid}"), callback_data=f"modinq_{cid}")]
                    for cid, nom, ci in inquilinos
                ]
                buttons.append([InlineKeyboardButton("Volver", callback_data='admin_menu_inquilinos')])
                await query.edit_message_text(
                    escape_markdown_v2("Selecciona el inquilino a modificar:"),
                    reply_markup=InlineKeyboardMarkup(buttons), parse_mode='MarkdownV2'
                )
        else:
            await query.edit_message_text(escape_markdown_v2("Opción no reconocida para administrador."), reply_markup=teclado_admin(), parse_mode='MarkdownV2')
    else:
        # --- Opciones inquilino ---
        if target_menu_data == 'menu_inquilino':
            inquilino = obtener_inquilino(chat_id)
            if inquilino and inquilino[3] is not None:
                await query.edit_message_text(
                    escape_markdown_v2("Menú inquilino:"), reply_markup=teclado_inquilino(), parse_mode='MarkdownV2'
                )
            else:
                await query.edit_message_text(
                    escape_markdown_v2("Tu registro está pendiente de validación por el administrador. Usa /start para verificar tu estado."),
                    parse_mode='MarkdownV2'
                )
        elif target_menu_data == 'ver_saldo':
            inquilino = obtener_inquilino(chat_id)

            if not inquilino:
                await query.edit_message_text(escape_markdown_v2("No estás registrado. Por favor, usa /start para iniciar el registro."),
                                              reply_markup=teclado_inquilino(), parse_mode='MarkdownV2')
                return ConversationHandler.END
            
            if inquilino[3] is None: # Si el inquilino no tiene fecha de ingreso, su registro está incompleto
                await query.edit_message_text(
                    escape_markdown_v2("Tu registro está pendiente de validación por el administrador. Por favor, espera a que el administrador complete tu registro para ver esta información."),
                    reply_markup=teclado_inquilino(), parse_mode='MarkdownV2'
                )
                return ConversationHandler.END


            nombre_inquilino = inquilino[1]
            monto_alquiler = inquilino[4] if inquilino[4] is not None else 0.0
            saldo_actual = inquilino[6] if inquilino[6] is not None else 0.0
            tipo_alquiler = inquilino[5]
            propiedad_id = inquilino[7]
            num_personas_inquilino = inquilino[11] if inquilino[11] is not None else 1

            texto = f"Hola {escape_markdown_v2(nombre_inquilino)},\n\n"
            texto += f"Tu alquiler mensual base es: *{monto_alquiler:.2f} Bs.*"
            texto += f"\nSaldo pendiente total: *{saldo_actual:.2f} Bs.*"
            texto += "\n\n"

            if tipo_alquiler == 'prorrateo':
                texto += "*Estimado de Servicios (Mes actual):*\n"
                total_servicios_prorrateo_estimado = 0.0
                current_year = datetime.now().year
                current_month = datetime.now().month

                medidor_luz_individual_id = inquilino[8]
                if medidor_luz_individual_id:
                    current_reading = obtener_ultima_lectura(medidor_luz_individual_id)
                    previous_reading = obtener_lectura_anterior_mes(medidor_luz_individual_id, current_year, current_month)
                    tenant_kwh_consumed = current_reading - previous_reading

                    cursor.execute("SELECT id FROM medidores WHERE propiedad_id = ? AND tipo_servicio = 'luz' LIMIT 1", (propiedad_id,))
                    main_luz_medidor_info = cursor.fetchone()
                    
                    costo_inquilino_luz = 0.0
                    if main_luz_medidor_info:
                        main_luz_medidor_id = main_luz_medidor_info[0]
                        main_luz_bill, main_luz_kwh_total = obtener_facturas_por_medidor_y_mes(main_luz_medidor_id, current_year, current_month)

                        if main_luz_kwh_total > 0:
                            cost_per_kwh = main_luz_bill / main_luz_kwh_total
                            costo_inquilino_luz = cost_per_kwh * tenant_kwh_consumed
                            texto += f"  - Luz (Consumo: {tenant_kwh_consumed:.2f} kWh): {costo_inquilino_luz:.2f} Bs. (Tarifa: {cost_per_kwh:.2f} Bs/kWh)\n"
                        else:
                            texto += f"  - Luz: No se pudo calcular (kWh total de factura principal 0 o no disponible).\n"
                    else:
                        texto += f"  - Luz: No se encontró medidor principal de luz para la propiedad.\n"
                    total_servicios_prorrateo_estimado += costo_inquilino_luz
                else:
                    texto += "  - Luz: Incluida en alquiler base (sin medidor individual asignado).\n"

                medidor_agua_main_id = inquilino[9]
                if medidor_agua_main_id:
                    medidor_info = obtener_medidor_por_id(medidor_agua_main_id)
                    if medidor_info:
                        cursor.execute("SELECT SUM(num_personas) FROM inquilinos WHERE medidor_asignado_agua_id = ?", (medidor_agua_main_id,))
                        total_personas_medidor_agua = cursor.fetchone()[0] or 1

                        main_agua_bill, _ = obtener_facturas_por_medidor_y_mes(medidor_agua_main_id, current_year, current_month)
                        costo_por_persona_agua = (main_agua_bill / total_personas_medidor_agua) if total_personas_medidor_agua > 0 else 0
                        costo_inquilino_agua = costo_por_persona_agua * num_personas_inquilino
                        total_servicios_prorrateo_estimado += costo_inquilino_agua
                        texto += f"  - Agua ({escape_markdown_v2(medidor_info[2])}): {costo_inquilino_agua:.2f} Bs. (Total medidor: {main_agua_bill:.2f} Bs. / {total_personas_medidor_agua} pers.)\n"
                else:
                    texto += "  - Agua: Incluida en alquiler base (sin medidor principal asignado).\n"

                medidor_gas_main_id = inquilino[10]
                if medidor_gas_main_id:
                    medidor_info = obtener_medidor_por_id(inquilino[10])
                    if medidor_info:
                        cursor.execute("SELECT SUM(num_personas) FROM inquilinos WHERE medidor_asignado_gas_id = ?", (medidor_gas_main_id,))
                        total_personas_medidor_gas = cursor.fetchone()[0] or 1

                        main_gas_bill, _ = obtener_facturas_por_medidor_y_mes(medidor_gas_main_id, current_year, current_month)
                        costo_por_persona_gas = (main_gas_bill / total_personas_medidor_gas) if total_personas_medidor_gas > 0 else 0
                        costo_inquilino_gas = costo_por_persona_gas * num_personas_inquilino
                        total_servicios_prorrateo_estimado += costo_inquilino_gas
                        texto += f"  - Gas ({escape_markdown_v2(medidor_info[2])}): {costo_inquilino_gas:.2f} Bs. (Total medidor: {main_gas_bill:.2f} Bs. / {total_personas_medidor_gas} pers.)\n"
                else:
                    texto += "  - Gas: Incluida en alquiler base (sin medidor principal asignado).\n"

                cursor.execute("SELECT id FROM medidores WHERE propiedad_id = ? AND tipo_servicio = 'internet_tv' LIMIT 1", (propiedad_id,))
                main_internet_tv_medidor_info = cursor.fetchone()
                
                costo_inquilino_internet_tv = 0.0
                if main_internet_tv_medidor_info:
                    main_internet_tv_medidor_id = main_internet_tv_medidor_info[0]
                    main_internet_tv_bill, _ = obtener_facturas_por_medidor_y_mes(main_internet_tv_medidor_id, current_year, current_month)
                    
                    cursor.execute("SELECT SUM(num_personas) FROM inquilinos WHERE propiedad_id = ?", (propiedad_id,))
                    total_personas_propiedad = cursor.fetchone()[0] or 1

                    costo_por_persona_internet_tv = (main_internet_tv_bill / total_personas_propiedad) if total_personas_propiedad > 0 else 0
                    costo_inquilino_internet_tv = costo_por_persona_internet_tv * num_personas_inquilino
                    total_servicios_prorrateo_estimado += costo_inquilino_internet_tv
                    texto += f"  - Internet/TV: {costo_inquilino_internet_tv:.2f} Bs. (Total propiedad: {main_internet_tv_bill:.2f} Bs. / {total_personas_propiedad} pers.)\n"
                else:
                    texto += "  - Internet/TV: No se encontró medidor principal de Internet/TV para la propiedad o no aplica.\n"

                texto += f"\nTotal estimado servicios: *{total_servicios_prorrateo_estimado:.2f} Bs.*"
                texto += f"\nTotal mensual estimado (Alquiler + Servicios): *{(monto_alquiler + total_servicios_prorrateo_estimado):.2f} Bs.*"
                texto += "\n\n"

            cursor.execute("SELECT fecha_pago, monto_pagado, confirmado FROM pagos WHERE chat_id = ? ORDER BY fecha_pago DESC LIMIT 5", (chat_id,))
            pagos_recientes = cursor.fetchall()
            if pagos_recientes:
                texto += "*Últimos pagos registrados:*\n"
                for fecha, monto, confirmado in pagos_recientes:
                    estado = "Confirmado" if confirmado else "Pendiente"
                    texto += f"- {fecha}: {monto:.2f} Bs. ({estado})\n"
            else:
                texto += "No hay pagos registrados.\n"

            await query.edit_message_text(escape_markdown_v2(texto), reply_markup=teclado_inquilino(), parse_mode='MarkdownV2')

        elif target_menu_data == 'ver_mi_propiedad':
            inquilino = obtener_inquilino(chat_id)

            if not inquilino or inquilino[7] is None: # inquilino[7] es propiedad_id
                await query.edit_message_text(escape_markdown_v2("No tienes una propiedad asignada aún. Contacta al administrador."),
                                              reply_markup=teclado_inquilino(), parse_mode='MarkdownV2')
                return ConversationHandler.END

            propiedad_id = inquilino[7]
            propiedad = obtener_propiedad_por_id(propiedad_id)

            if propiedad:
                texto = (
                    f"🏡 *Detalles de tu Propiedad* 🏡\n\n"
                    f"*Nombre:* {escape_markdown_v2(propiedad[1])}\n"
                    f"*Dirección:* {escape_markdown_v2(propiedad[2])}\n\n"
                    f"🌐 *Información Wi-Fi:*\n"
                    f"  - *SSID:* `{escape_markdown_v2(propiedad[3] if propiedad[3] else 'No asignado')}`\n"
                    f"  - *Contraseña:* `{escape_markdown_v2(propiedad[4] if propiedad[4] else 'No asignado')}`\n"
                )
                
                has_medidores = False
                medidor_luz = obtener_medidor_por_id(inquilino[8]) if inquilino[8] else None
                medidor_agua = obtener_medidor_por_id(inquilino[9]) if inquilino[9] else None
                medidor_gas = obtener_medidor_por_id(inquilino[10]) if inquilino[10] else None

                if medidor_luz or medidor_agua or medidor_gas:
                    texto += "\n⚡💧🔥 *Tus Medidores Asignados:*\n"
                    has_medidores = True

                if medidor_luz:
                    texto += f"  - *Luz:* {escape_markdown_v2(medidor_luz[2])} (Tipo: {escape_markdown_v2(medidor_luz[3].capitalize())})\n"
                if medidor_agua:
                    texto += f"  - *Agua:* {escape_markdown_v2(medidor_agua[2])} (Tipo: {escape_markdown_v2(medidor_agua[3].capitalize())})\n"
                if medidor_gas:
                    texto += f"  - *Gas:* {escape_markdown_v2(medidor_gas[2])} (Tipo: {escape_markdown_v2(medidor_gas[3].capitalize())})\n"

                if not has_medidores:
                    texto += "\n_No tienes medidores de servicios asignados a tu propiedad._\n"

                await query.edit_message_text(escape_markdown_v2(texto), reply_markup=teclado_inquilino(), parse_mode='MarkdownV2')
            else:
                await query.edit_message_text(escape_markdown_v2("No se encontró la información de tu propiedad. Contacta al administrador."),
                                              reply_markup=teclado_inquilino(), parse_mode='MarkdownV2')
        else:
            await query.edit_message_text(escape_markdown_v2("Opción no reconocida para inquilino."), reply_markup=teclado_inquilino(), parse_mode='MarkdownV2')
    return ConversationHandler.END

async def cancelar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Permite al usuario cancelar la operación actual."""
    chat_id = update.effective_chat.id
    message_to_edit = None

    if update.message:
        message_to_edit = update.message
    elif update.callback_query:
        message_to_edit = update.callback_query.message
        await update.callback_query.answer()

    if message_to_edit:
        if chat_id in ADMIN_IDS:
            await message_to_edit.edit_text(escape_markdown_v2("Operación cancelada."), reply_markup=teclado_admin(), parse_mode='MarkdownV2')
        else:
            await message_to_edit.edit_text(escape_markdown_v2("Operación cancelada."), reply_markup=teclado_inquilino(), parse_mode='MarkdownV2')
    else:
        if chat_id in ADMIN_IDS:
            await context.bot.send_message(chat_id=chat_id, text=escape_markdown_v2("Operación cancelada."), reply_markup=teclado_admin(), parse_mode='MarkdownV2')
        else:
            await context.bot.send_message(chat_id=chat_id, text=escape_markdown_v2("Operación cancelada."), reply_markup=teclado_inquilino(), parse_mode='MarkdownV2')
            
    return ConversationHandler.END

# --- Configuración de los handlers de conversación ---

conv_handler = ConversationHandler(
    entry_points=[
        CommandHandler('start', start),
        # Puntos de entrada para los clics iniciales de menú que inician conversaciones
        # Los submenús de admin ahora son puntos de entrada directos
        CallbackQueryHandler(handle_admin_menu_inquilinos, pattern='^admin_menu_inquilinos$'),
        CallbackQueryHandler(handle_admin_menu_facturacion, pattern='^admin_menu_facturacion$'),
        CallbackQueryHandler(handle_admin_menu_comunicacion, pattern='^admin_menu_comunicacion$'),

        # Acciones de inquilino que pueden iniciar una conversación
        CallbackQueryHandler(handle_amortizar_callback, pattern='^amortizar$'),
        CallbackQueryHandler(handle_queja_callback, pattern='^queja$'),
        CallbackQueryHandler(ver_mi_propiedad, pattern='^ver_mi_propiedad$'),
        CallbackQueryHandler(ver_saldo_y_pagos, pattern='^ver_saldo$'),

        # Acciones de administrador que pueden iniciar una conversación (ahora desde submenús)
        CallbackQueryHandler(handle_admin_reg_inquilino_callback, pattern='^admin_reg_inquilino$'),
        CallbackQueryHandler(handle_admin_modificar_inquilino_callback, pattern='^admin_modificar_inquilino$'),
        CallbackQueryHandler(handle_admin_nuevo_inquilino_callback, pattern='^admin_nuevo_inquilino$'),
        CallbackQueryHandler(handle_admin_eliminar_inquilino_callback, pattern='^admin_eliminar_inquilino$'),
        CallbackQueryHandler(handle_admin_reg_factura_callback, pattern='^admin_reg_factura$'),
        CallbackQueryHandler(handle_admin_reg_lectura_callback, pattern='^admin_reg_lectura$'),
        CallbackQueryHandler(handle_admin_gestionar_propiedades_callback, pattern='^admin_gestionar_propiedades$'),
        CallbackQueryHandler(handle_admin_add_propiedad_callback, pattern='^admin_add_propiedad$'),
        CallbackQueryHandler(handle_admin_del_propiedad_callback, pattern='^admin_del_propiedad$'),
        CallbackQueryHandler(handle_admin_add_medidor_callback, pattern='^admin_add_medidor$'),
        CallbackQueryHandler(handle_admin_send_notice_callback, pattern='^admin_send_notice$'),
        CallbackQueryHandler(handle_admin_confirmar_pagos_callback, pattern='^admin_confirmar_pagos$'),
        CallbackQueryHandler(handle_admin_quejas_callback, pattern='^admin_quejas$'),
        CallbackQueryHandler(handle_admin_generar_cobro_mensual_callback, pattern='^admin_generar_cobro_mensual$'),
        CallbackQueryHandler(admin_show_accounting_summary, pattern='^admin_resumen_contable$'),
        CallbackQueryHandler(handle_admin_modificar_propiedad_callback, pattern='^admin_modificar_propiedad$'), # Nuevo handler

        CallbackQueryHandler(menu_callback, pattern='^admin_morosos$'),
        CallbackQueryHandler(admin_ver_propiedades_callback, pattern='^admin_ver_propiedades$'),
    ],
    states={
        REGISTRAR_NOMBRE: [MessageHandler(filters.TEXT & ~filters.COMMAND, registrar_nombre)],
        REGISTRAR_CI: [MessageHandler(filters.TEXT & ~filters.COMMAND, registrar_ci)],

        ADMIN_REG_INQUILINO_SELECT: [CallbackQueryHandler(handle_reginqui_selection_callback, pattern='^reginqui_')],
        ADMIN_REG_FECHA: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_reg_fecha)],
        ADMIN_REG_ALQUILER: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_reg_monto)],
        ADMIN_REG_TIPO_ALQ: [CallbackQueryHandler(admin_reg_tipo, pattern='^tipo_')],
        ADMIN_REG_NUM_PERSONAS: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_reg_num_personas)],
        ADMIN_REG_INQ_MEDIDOR_LUZ: [CallbackQueryHandler(admin_reg_inq_medidor_luz, pattern='^medluz_sel_')],
        ADMIN_REG_INQ_MEDIDOR_AGUA: [CallbackQueryHandler(admin_reg_inq_medidor_agua, pattern='^medagua_sel_')],
        ADMIN_REG_INQ_MEDIDOR_GAS: [CallbackQueryHandler(admin_reg_inq_medidor_gas, pattern='^medgas_sel_')],
        ADMIN_REG_INQUILINO_PROPIEDAD: [CallbackQueryHandler(admin_reg_inquilino_propiedad, pattern='^propiedad_sel_')], # Asegura que este handler esté aquí

        INQ_AMORTIZAR_MONTO: [MessageHandler(filters.TEXT & ~filters.COMMAND, inq_amortizar_monto)],
        INQ_AMORTIZAR_COMPROBANTE: [MessageHandler(filters.PHOTO & ~filters.COMMAND, inq_amortizar_comprobante)],

        INQ_ENVIAR_QUEJA: [MessageHandler(filters.TEXT & ~filters.COMMAND, inq_enviar_queja)],

        ADMIN_REG_FACTURA_PROPIEDAD: [CallbackQueryHandler(admin_reg_factura_propiedad, pattern='^factprop_')],
        ADMIN_REG_FACTURA_SERVICIO_TIPO: [CallbackQueryHandler(admin_reg_factura_servicio_tipo, pattern='^servicio_')],
        ADMIN_REG_FACTURA_MONTO: [
            CallbackQueryHandler(admin_reg_factura_monto, pattern='^factmed_'), # Selección de medidor
            MessageHandler(filters.TEXT & ~filters.COMMAND, admin_reg_factura_monto) # Entrada de monto
        ],

        ADMIN_REG_LECTURA_PROPIEDAD: [CallbackQueryHandler(admin_reg_lectura_propiedad, pattern='^lectprop_')],
        ADMIN_REG_LECTURA_MEDIDOR_SELECT: [CallbackQueryHandler(admin_reg_lectura_medidor_select, pattern='^lectmed_')],
        ADMIN_REG_LECTURA_VALOR: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_reg_lectura_valor)],

        NOMBRE: [MessageHandler(filters.TEXT & ~filters.COMMAND, obtener_nombre_manual)],

        ADMIN_ELIMINAR_INQUILINO_SELECT: [CallbackQueryHandler(admin_eliminar_inquilino_select, pattern='^delinqui_')],
        ADMIN_ELIMINAR_INQUILINO_CONFIRM: [CallbackQueryHandler(admin_eliminar_inquilino_confirm, pattern='^(confirm_del_inquilino|cancel_del_inquilino)$')],

        ADMIN_PROPIEDADES_MENU: [
            CallbackQueryHandler(admin_ver_propiedades_callback, pattern='^admin_ver_propiedades$'),
            CallbackQueryHandler(handle_admin_add_propiedad_callback, pattern='^admin_add_propiedad$'),
            CallbackQueryHandler(handle_admin_del_propiedad_callback, pattern='^admin_del_propiedad$'),
            CallbackQueryHandler(handle_admin_add_medidor_callback, pattern='^admin_add_medidor$'),
            CallbackQueryHandler(handle_admin_modificar_propiedad_callback, pattern='^admin_modificar_propiedad$'), # Nuevo handler
            CallbackQueryHandler(menu_callback, pattern='^admin_menu_facturacion$') # Para volver al submenu de facturación
        ],
        ADMIN_ADD_PROPIEDAD_NOMBRE: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_add_propiedad_nombre)],
        ADMIN_ADD_PROPIEDAD_DIRECCION: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_add_propiedad_direccion)],
        ADMIN_ADD_PROPIEDAD_SSID: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_add_propiedad_ssid)],
        ADMIN_ADD_PROPIEDAD_WIFI: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_add_propiedad_wifi)],

        ADMIN_DEL_PROPIEDAD_SELECT: [CallbackQueryHandler(admin_del_propiedad_select, pattern='^delprop_')],
        ADMIN_DEL_PROPIEDAD_CONFIRM: [CallbackQueryHandler(admin_del_propiedad_confirm, pattern='^(confirm_del_propiedad|cancel_del_propiedad)$')],

        ADMIN_MODIFICAR_PROPIEDAD_SELECT: [CallbackQueryHandler(admin_modificar_propiedad_select, pattern='^modprop_')],
        ADMIN_MODIFICAR_PROPIEDAD_FIELD: [CallbackQueryHandler(admin_modificar_propiedad_field, pattern='^mod_prop_')],
        ADMIN_MODIFICAR_PROPIEDAD_VALUE: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, admin_modificar_propiedad_value),
            CallbackQueryHandler(admin_modificar_propiedad_value, pattern='^mod_val_') # Para selecciones de tipo/propiedad/medidor
        ],


        ADMIN_ADD_MEDIDOR_PROPIEDAD_SELECT: [CallbackQueryHandler(admin_add_medidor_propiedad_select, pattern='^addmedprop_')],
        ADMIN_ADD_MEDIDOR_NOMBRE: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_add_medidor_nombre)],
        ADMIN_ADD_MEDIDOR_TIPO: [CallbackQueryHandler(admin_add_medidor_tipo, pattern='^servicio_')],

        ADMIN_SEND_NOTICE_SCOPE: [CallbackQueryHandler(admin_send_notice_scope_select, pattern='^notice_scope_')],
        ADMIN_SEND_NOTICE_PROPERTY_SELECT: [CallbackQueryHandler(admin_send_notice_property_select, pattern='^noticeprop_')],
        ADMIN_SEND_NOTICE_INQUILINO_SELECT: [CallbackQueryHandler(admin_send_notice_inquilino_select, pattern='^noticeinq_')],
        ADMIN_SEND_NOTICE_MESSAGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_send_notice_message)],

        ADMIN_CONFIRM_PAGO_SELECT: [CallbackQueryHandler(admin_confirm_pago_select, pattern='^confirmpago_')],
        ADMIN_CONFIRM_PAGO_CONFIRM: [CallbackQueryHandler(admin_confirm_pago_confirm, pattern='^(confirm_pago_yes|confirm_pago_no)$')],

        ADMIN_MARK_QUEJA_RESOLVED_SELECT: [CallbackQueryHandler(admin_mark_queja_resolved_select, pattern='^markqueja_')],
        ADMIN_MARK_QUEJA_RESOLVED_CONFIRM: [CallbackQueryHandler(admin_mark_queja_resolved_confirm, pattern='^(confirm_resolve_queja|cancel_resolve_queja)$')],

        ADMIN_MODIFICAR_INQUILINO_SELECT: [CallbackQueryHandler(admin_modificar_inquilino_select, pattern='^modinq_')],
        ADMIN_MODIFICAR_INQUILINO_FIELD: [CallbackQueryHandler(admin_modificar_inquilino_field, pattern='^mod_inq_')],
        ADMIN_MODIFICAR_INQUILINO_VALUE: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, admin_modificar_inquilino_value),
            CallbackQueryHandler(admin_modificar_inquilino_value, pattern='^mod_val_') # Para selecciones de tipo/propiedad/medidor
        ],
        ADMIN_GENERAR_COBRO_MENSUAL_SCOPE: [CallbackQueryHandler(admin_generar_cobro_mensual_scope, pattern='^charge_scope_')],
        ADMIN_GENERAR_COBRO_MENSUAL_PROPERTY_SELECT: [CallbackQueryHandler(admin_generar_cobro_mensual_property_select, pattern='^chargeprop_')],
        ADMIN_GENERAR_COBRO_MENSUAL_CONFIRM: [CallbackQueryHandler(admin_generar_cobro_mensual_confirm, pattern='^charge_confirm_|^charge_cancel$')],
    },
    fallbacks=[
        CommandHandler('cancelar', cancelar),
        CallbackQueryHandler(menu_callback, pattern='^(menu_admin|menu_inquilino|admin_menu_inquilinos|admin_menu_facturacion|admin_menu_comunicacion|admin_gestionar_propiedades|admin_modificar_inquilino|admin_morosos|admin_ver_propiedades|admin_resumen_contable|ver_saldo|ver_mi_propiedad)$')
    ],
    allow_reentry=True
)

# --- Configuración de comandos persistentes del bot ---
async def set_default_commands(application):
    """Establece los comandos por defecto para el bot (botón de menú)."""
    commands = [
        BotCommand("start", "Iniciar o ir al menú principal"),
        BotCommand("cancelar", "Cancelar operación actual"),
    ]
    await application.bot.set_my_commands(commands)
    logger.info("Comandos por defecto del bot configurados.")

# --- Función principal ---

def main():
    """Función principal para iniciar el bot."""
    application = ApplicationBuilder().token(TOKEN).build()

    # Configurar los comandos persistentes del bot
    application.job_queue.run_once(set_default_commands, 0, name="set_default_commands")

    # Añadir handlers
    application.add_handler(conv_handler)

    logger.info("Bot corriendo...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
