import os
import json
import logging
import pyodbc
import azure.functions as func
from password import hash_password
from password import verify_password
from voice_assessment import assess_pronunciation, VoiceAssessmentError
from voice_recognition import recognize_speech
from voice_comparison import compare_transcription

app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)

def check_api_key(req: func.HttpRequest) -> bool:
    expected_key = os.environ.get("API_KEY")
    provided_key = req.headers.get("X-API-Key")

    if not expected_key or not provided_key:
        return False

    return provided_key == expected_key

@app.route(route="login", methods=["POST"])
def login_user(req: func.HttpRequest) -> func.HttpResponse:
    logging.info("POST /api/login")

    if not check_api_key(req):
        return func.HttpResponse(
            json.dumps({
                "error": "Unauthorized"
            }),
            status_code=401,
            mimetype="application/json"
        )

    # =========================================================
    # JSON BODY
    # =========================================================

    try:
        body = req.get_json()
    except ValueError:
        return func.HttpResponse(
            json.dumps({
                "error": "Invalid JSON"
            }, ensure_ascii=False),
            status_code=400,
            mimetype="application/json"
        )

    if not isinstance(body, dict):
        return func.HttpResponse(
            json.dumps({
                "error": "JSON body must be an object"
            }, ensure_ascii=False),
            status_code=400,
            mimetype="application/json"
        )

    nickname = body.get("nickname")
    password = body.get("password")

    if not nickname:
        return func.HttpResponse(
            json.dumps({
                "error": "Missing nickname"
            }, ensure_ascii=False),
            status_code=400,
            mimetype="application/json"
        )

    if not password:
        return func.HttpResponse(
            json.dumps({
                "error": "Missing password"
            }, ensure_ascii=False),
            status_code=400,
            mimetype="application/json"
        )

    # =========================================================
    # DATABASE
    # =========================================================

    try:
        connection_string = os.environ["SQL_CONNECTION_STRING"]

        with pyodbc.connect(
            connection_string,
            timeout=10
        ) as conn:

            cursor = conn.cursor()

            cursor.execute(
                """
                SELECT
                    us_id,
                    us_nicname,
                    us_first_name,
                    us_last_name,
                    us_password_hash,
                    us_active
                FROM dbo.users
                WHERE us_nicname = ?
                """,
                nickname
            )

            row = cursor.fetchone()

            # -------------------------------------------------
            # Пользователь не найден
            # -------------------------------------------------

            if row is None:
                return func.HttpResponse(
                    json.dumps({
                        "error": "Invalid credentials"
                    }, ensure_ascii=False),
                    status_code=401,
                    mimetype="application/json"
                )

            # -------------------------------------------------
            # Данные пользователя
            # -------------------------------------------------

            user_id = row[0]
            user_nickname = row[1]
            first_name = row[2]
            last_name = row[3]
            password_hash = row[4]
            active = row[5]

            # -------------------------------------------------
            # Проверка активности
            # -------------------------------------------------

            if not active:
                return func.HttpResponse(
                    json.dumps({
                        "error": "User account is inactive"
                    }, ensure_ascii=False),
                    status_code=403,
                    mimetype="application/json"
                )

            # -------------------------------------------------
            # Проверка пароля
            # -------------------------------------------------

            if not password_hash:
                return func.HttpResponse(
                    json.dumps({
                        "error": "Invalid credentials"
                    }, ensure_ascii=False),
                    status_code=401,
                    mimetype="application/json"
                )

            if not verify_password(
                password,
                password_hash
            ):
                return func.HttpResponse(
                    json.dumps({
                        "error": "Invalid credentials"
                    }, ensure_ascii=False),
                    status_code=401,
                    mimetype="application/json"
                )

            # -------------------------------------------------
            # Успешный login
            # -------------------------------------------------

            return func.HttpResponse(
                json.dumps({
                    "user_id": user_id,
                    "nickname": user_nickname,
                    "first_name": first_name,
                    "last_name": last_name,
                    "active": active
                }, ensure_ascii=False),
                status_code=200,
                mimetype="application/json"
            )

    except Exception as e:

        logging.exception(
            "POST /api/login failed"
        )

        return func.HttpResponse(
            json.dumps({
                "error": "Internal server error",
                "message": str(e)
            }, ensure_ascii=False),
            status_code=500,
            mimetype="application/json"
        )


@app.route(route="register", methods=["POST"])
def register_user(req: func.HttpRequest) -> func.HttpResponse:
    logging.info("POST /api/register")

    # =========================================================
    # API KEY
    # =========================================================

    if not check_api_key(req):
        return func.HttpResponse(
            json.dumps({
                "error": "Unauthorized"
            }, ensure_ascii=False),
            status_code=401,
            mimetype="application/json"
        )

    # =========================================================
    # JSON BODY
    # =========================================================

    try:
        body = req.get_json()

    except ValueError:
        return func.HttpResponse(
            json.dumps({
                "error": "Invalid JSON"
            }, ensure_ascii=False),
            status_code=400,
            mimetype="application/json"
        )

    if not isinstance(body, dict):
        return func.HttpResponse(
            json.dumps({
                "error": "JSON body must be an object"
            }, ensure_ascii=False),
            status_code=400,
            mimetype="application/json"
        )

    # =========================================================
    # PARAMETERS
    # =========================================================

    nickname = body.get("nickname")
    password = body.get("password")

    first_name = body.get("first_name")
    last_name = body.get("last_name")

    if not nickname:
        return func.HttpResponse(
            json.dumps({
                "error": "Missing nickname"
            }, ensure_ascii=False),
            status_code=400,
            mimetype="application/json"
        )

    if not password:
        return func.HttpResponse(
            json.dumps({
                "error": "Missing password"
            }, ensure_ascii=False),
            status_code=400,
            mimetype="application/json"
        )

    # =========================================================
    # PASSWORD HASH
    # =========================================================

    try:
        password_hash = hash_password(password)

    except Exception:
        logging.exception(
            "Password hashing failed"
        )

        return func.HttpResponse(
            json.dumps({
                "error": "Password hashing failed"
            }, ensure_ascii=False),
            status_code=500,
            mimetype="application/json"
        )

    # =========================================================
    # DATABASE
    # =========================================================

    try:
        connection_string = os.environ["SQL_CONNECTION_STRING"]

        with pyodbc.connect(
            connection_string,
            timeout=10
        ) as conn:

            cursor = conn.cursor()

            cursor.execute(
                """
                EXEC dbo.sp_register_user
                    @us_nicname = ?,
                    @us_first_name = ?,
                    @us_last_name = ?,
                    @us_password_hash = ?
                """,
                nickname,
                first_name,
                last_name,
                password_hash
            )

            row = cursor.fetchone()

            if row is None:
                return func.HttpResponse(
                    json.dumps({
                        "error": "User was not created"
                    }, ensure_ascii=False),
                    status_code=500,
                    mimetype="application/json"
                )

            columns = [
                column[0]
                for column in cursor.description
            ]

            user = dict(
                zip(columns, row)
            )

            # datetime2 → JSON string
            if user["us_create_date"] is not None:
                user["us_create_date"] = (
                    user["us_create_date"].isoformat()
                )

            if user["us_update_date"] is not None:
                user["us_update_date"] = (
                    user["us_update_date"].isoformat()
                )

            return func.HttpResponse(
                json.dumps(
                    {
                        "user_id": user["us_id"],
                        "nickname": user["us_nicname"],
                        "first_name": user["us_first_name"],
                        "last_name": user["us_last_name"],
                        "active": user["us_active"]
                    },
                    ensure_ascii=False
                ),
                status_code=201,
                mimetype="application/json"
            )

    except pyodbc.Error as e:

        logging.exception(
            "POST /api/register database error"
        )

        error_message = str(e)

        # -----------------------------------------------------
        # Nickname already exists
        # -----------------------------------------------------

        if "(50001)" in error_message:

            return func.HttpResponse(
                json.dumps({
                    "error": "Nickname already exists",
                    "nickname": nickname
                }, ensure_ascii=False),
                status_code=409,
                mimetype="application/json"
            )

        # -----------------------------------------------------
        # Unknown database error
        # -----------------------------------------------------

        return func.HttpResponse(
            json.dumps({
                "error": "Database error",
                "message": error_message
            }, ensure_ascii=False),
            status_code=500,
            mimetype="application/json"
        )

    except Exception as e:

        logging.exception(
            "POST /api/register failed"
        )

        return func.HttpResponse(
            json.dumps({
                "error": "Internal server error",
                "message": str(e)
            }, ensure_ascii=False),
            status_code=500,
            mimetype="application/json"
        )

@app.route(route="change-password", methods=["POST"])
def change_password_user(req: func.HttpRequest) -> func.HttpResponse:
    logging.info("POST /api/change-password")

    # =========================================================
    # API KEY
    # =========================================================

    if not check_api_key(req):
        return func.HttpResponse(
            json.dumps({
                "error": "Unauthorized"
            }, ensure_ascii=False),
            status_code=401,
            mimetype="application/json"
        )

    # =========================================================
    # JSON BODY
    # =========================================================

    try:
        body = req.get_json()

    except ValueError:
        return func.HttpResponse(
            json.dumps({
                "error": "Invalid JSON"
            }, ensure_ascii=False),
            status_code=400,
            mimetype="application/json"
        )

    if not isinstance(body, dict):
        return func.HttpResponse(
            json.dumps({
                "error": "JSON body must be an object"
            }, ensure_ascii=False),
            status_code=400,
            mimetype="application/json"
        )

    # =========================================================
    # PARAMETERS
    # =========================================================

    user_id = body.get("user_id")
    current_password = body.get("current_password")
    new_password = body.get("new_password")

    if not user_id:
        return func.HttpResponse(
            json.dumps({
                "error": "Missing user_id"
            }, ensure_ascii=False),
            status_code=400,
            mimetype="application/json"
        )

    if not current_password:
        return func.HttpResponse(
            json.dumps({
                "error": "Missing current password"
            }, ensure_ascii=False),
            status_code=400,
            mimetype="application/json"
        )

    if not new_password:
        return func.HttpResponse(
            json.dumps({
                "error": "Missing new password"
            }, ensure_ascii=False),
            status_code=400,
            mimetype="application/json"
        )

    # =========================================================
    # DATABASE
    # =========================================================

    try:
        connection_string = os.environ["SQL_CONNECTION_STRING"]

        with pyodbc.connect(
            connection_string,
            timeout=10
        ) as conn:

            cursor = conn.cursor()

            cursor.execute(
                """
                SELECT
                    us_id,
                    us_nicname,
                    us_password_hash,
                    us_active
                FROM dbo.users
                WHERE us_id = ?
                  AND us_nicname <> N'guest'
                """,
                user_id
            )

            row = cursor.fetchone()

            # -------------------------------------------------
            # Пользователь не найден
            # -------------------------------------------------

            if row is None:
                return func.HttpResponse(
                    json.dumps({
                        "error": "User not found"
                    }, ensure_ascii=False),
                    status_code=404,
                    mimetype="application/json"
                )

            user_id = row[0]
            nickname = row[1]
            password_hash = row[2]
            active = row[3]

            # -------------------------------------------------
            # Проверка активности
            # -------------------------------------------------

            if not active:
                return func.HttpResponse(
                    json.dumps({
                        "error": "User account is inactive"
                    }, ensure_ascii=False),
                    status_code=403,
                    mimetype="application/json"
                )

            # -------------------------------------------------
            # Проверка текущего пароля
            # -------------------------------------------------

            if not password_hash:
                return func.HttpResponse(
                    json.dumps({
                        "error": "Current password is invalid"
                    }, ensure_ascii=False),
                    status_code=401,
                    mimetype="application/json"
                )

            if not verify_password(
                current_password,
                password_hash
            ):
                return func.HttpResponse(
                    json.dumps({
                        "error": "Current password is incorrect"
                    }, ensure_ascii=False),
                    status_code=401,
                    mimetype="application/json"
                )

            # -------------------------------------------------
            # Новый пароль
            # -------------------------------------------------

            try:
                new_password_hash = hash_password(
                    new_password
                )

            except Exception:
                logging.exception(
                    "Password hashing failed"
                )

                return func.HttpResponse(
                    json.dumps({
                        "error": "Password hashing failed"
                    }, ensure_ascii=False),
                    status_code=500,
                    mimetype="application/json"
                )

            # -------------------------------------------------
            # Изменение пароля
            # -------------------------------------------------

            cursor.execute(
                """
                EXEC dbo.sp_change_user_password
                    @us_id = ?,
                    @us_password_hash = ?
                """,
                user_id,
                new_password_hash
            )

            result = cursor.fetchone()

            if result is None:
                return func.HttpResponse(
                    json.dumps({
                        "error": "Password was not changed"
                    }, ensure_ascii=False),
                    status_code=500,
                    mimetype="application/json"
                )

            conn.commit()

            # -------------------------------------------------
            # Успешное изменение
            # -------------------------------------------------

            return func.HttpResponse(
                json.dumps({
                    "user_id": user_id,
                    "nickname": nickname,
                    "message": "Password changed successfully"
                }, ensure_ascii=False),
                status_code=200,
                mimetype="application/json"
            )

    except pyodbc.Error as e:

        logging.exception(
            "POST /api/change-password database error"
        )

        return func.HttpResponse(
            json.dumps({
                "error": "Database error",
                "message": str(e)
            }, ensure_ascii=False),
            status_code=500,
            mimetype="application/json"
        )

    except Exception as e:

        logging.exception(
            "POST /api/change-password failed"
        )

        return func.HttpResponse(
            json.dumps({
                "error": "Internal server error",
                "message": str(e)
            }, ensure_ascii=False),
            status_code=500,
            mimetype="application/json"
        )


@app.route(route="hello")
def hello(req: func.HttpRequest) -> func.HttpResponse:
    logging.info('Python HTTP trigger function processed a request.')

    name = req.params.get('name')

    if not name:
        try:
            req_body = req.get_json()
        except ValueError:
            pass
        else:
            name = req_body.get('name')

    if name:
        return func.HttpResponse(
            f"Hello, {name}. This HTTP triggered function executed successfully."
        )

    return func.HttpResponse(
        "This HTTP triggered function executed successfully. "
        "Pass a name in the query string or in the request body "
        "for a personalized response.",
        status_code=200
    )


@app.route(route="db-test")
def db_test(req: func.HttpRequest) -> func.HttpResponse:
    logging.info("Testing Azure SQL connection.")

    connection_string = os.environ.get("SQL_CONNECTION_STRING")

    if not connection_string:
        return func.HttpResponse(
            "SQL_CONNECTION_STRING is not configured.",
            status_code=500
        )

    try:
        with pyodbc.connect(connection_string, timeout=10) as connection:
            cursor = connection.cursor()
            cursor.execute("SELECT 1")
            row = cursor.fetchone()

            return func.HttpResponse(
                f"Database connection successful. SELECT 1 returned: {row[0]}",
                status_code=200
            )

    except Exception as e:
        logging.exception("Database connection failed.")

        return func.HttpResponse(
            f"Database connection failed: {str(e)}",
            status_code=500
        )

@app.route(route="sets", methods=["GET"])
def get_sets(req: func.HttpRequest) -> func.HttpResponse:
    logging.info("GET /api/sets")

    if not check_api_key(req):
        return func.HttpResponse(
            json.dumps({"error": "Unauthorized"}),
            status_code=401,
            mimetype="application/json"
        )

    # =========================================================
    # PARAMETERS
    # =========================================================

    user_id = req.params.get("user_id")

    if not user_id:
        return func.HttpResponse(
            json.dumps({
                "error": "Missing user_id"
            }, ensure_ascii=False),
            status_code=400,
            mimetype="application/json"
        )

    try:
        user_id = int(user_id)
    except ValueError:
        return func.HttpResponse(
            json.dumps({
                "error": "Invalid user_id"
            }, ensure_ascii=False),
            status_code=400,
            mimetype="application/json"
        )

    # =========================================================
    # DATABASE
    # =========================================================

    try:
        connection_string = os.environ["SQL_CONNECTION_STRING"]

        with pyodbc.connect(connection_string, timeout=10) as conn:
            cursor = conn.cursor()

            cursor.execute("""
                SELECT
                    v.set_id,
                    v.user_id,
                    v.user_nickname,
                    v.set_index,
                    v.set_name,
                    v.set_description,
                    v.set_active,
                    v.set_create_date,
                    v.set_update_date,
                    v.items_count,
                    s.se_mobile_audio_ready_at
                        AS mobile_audio_ready_at
                FROM vw_sets AS v
                INNER JOIN dbo.sets AS s
                    ON s.se_id = v.set_id
                WHERE v.user_id = ?
                ORDER BY v.set_index
            """, user_id)

            columns = [column[0] for column in cursor.description]

            rows = []

            for row in cursor.fetchall():
                item = dict(zip(columns, row))

                # datetime2 → строка JSON
                for date_field in (
                    "set_create_date",
                    "set_update_date",
                    "mobile_audio_ready_at"
                ):
                    if item[date_field] is not None:
                        item[date_field] = (
                            item[date_field].isoformat()
                        )

                rows.append(item)

            return func.HttpResponse(
                json.dumps(rows, ensure_ascii=False),
                status_code=200,
                mimetype="application/json"
            )

    except Exception as e:
        logging.exception("GET /api/sets failed")

        return func.HttpResponse(
            json.dumps({
                "error": "Database error",
                "message": str(e)
            }, ensure_ascii=False),
            status_code=500,
            mimetype="application/json"
        )
    
@app.route(route="mobile/sets", methods=["GET"])
def get_mobile_ready_sets(req: func.HttpRequest) -> func.HttpResponse:
    logging.info("GET /api/mobile/sets")

    # =========================================================
    # API KEY
    # =========================================================

    if not check_api_key(req):
        return func.HttpResponse(
            json.dumps({"error": "Unauthorized"}),
            status_code=401,
            mimetype="application/json"
        )

    # =========================================================
    # PARAMETERS
    # =========================================================

    user_id = req.params.get("user_id")

    if not user_id:
        return func.HttpResponse(
            json.dumps({
                "error": "Missing user_id"
            }, ensure_ascii=False),
            status_code=400,
            mimetype="application/json"
        )

    try:
        user_id = int(user_id)
    except ValueError:
        return func.HttpResponse(
            json.dumps({
                "error": "Invalid user_id"
            }, ensure_ascii=False),
            status_code=400,
            mimetype="application/json"
        )

    # =========================================================
    # DATABASE
    # =========================================================

    try:
        connection_string = os.environ["SQL_CONNECTION_STRING"]

        with pyodbc.connect(
            connection_string,
            timeout=10
        ) as conn:
            cursor = conn.cursor()

            cursor.execute("""
                SELECT
                    v.set_id,
                    v.user_id,
                    v.user_nickname,
                    v.set_index,
                    v.set_name,
                    v.set_description,
                    v.set_active,
                    v.set_create_date,
                    v.set_update_date,
                    v.items_count,
                    s.se_mobile_audio_ready_at
                        AS mobile_audio_ready_at
                FROM vw_sets AS v
                INNER JOIN dbo.sets AS s
                    ON s.se_id = v.set_id
                WHERE v.user_id = ?
                  AND s.se_mobile_audio_ready_at IS NOT NULL
                ORDER BY v.set_index
            """, user_id)

            columns = [
                column[0]
                for column in cursor.description
            ]

            rows = []

            for row in cursor.fetchall():
                item = dict(zip(columns, row))

                for date_field in (
                    "set_create_date",
                    "set_update_date",
                    "mobile_audio_ready_at"
                ):
                    if item[date_field] is not None:
                        item[date_field] = (
                            item[date_field].isoformat()
                        )

                rows.append(item)

            return func.HttpResponse(
                json.dumps(rows, ensure_ascii=False),
                status_code=200,
                mimetype="application/json"
            )

    except Exception as e:
        logging.exception(
            "GET /api/mobile/sets failed"
        )

        return func.HttpResponse(
            json.dumps({
                "error": "Database error",
                "message": str(e)
            }, ensure_ascii=False),
            status_code=500,
            mimetype="application/json"
        )

@app.route(route="sets/{set_id}", methods=["GET"])
def get_set(req: func.HttpRequest) -> func.HttpResponse:
    logging.info("GET /api/sets/{set_id}")

    if not check_api_key(req):
        return func.HttpResponse(
            json.dumps({"error": "Unauthorized"}),
            status_code=401,
            mimetype="application/json"
        )

    set_id = req.route_params.get("set_id")

    if not set_id:
        return func.HttpResponse(
            json.dumps({
                "error": "Missing set_id"
            }, ensure_ascii=False),
            status_code=400,
            mimetype="application/json"
        )

    try:
        set_id = int(set_id)
    except ValueError:
        return func.HttpResponse(
            json.dumps({
                "error": "Invalid set_id"
            }, ensure_ascii=False),
            status_code=400,
            mimetype="application/json"
        )

    try:
        connection_string = os.environ["SQL_CONNECTION_STRING"]

        with pyodbc.connect(connection_string, timeout=10) as conn:
            cursor = conn.cursor()

            cursor.execute("""
                SELECT
                    set_id,
                    user_id,
                    user_nickname,
                    set_index,
                    set_name,
                    set_description,
                    set_active,
                    set_create_date,
                    set_update_date,
                    items_count
                FROM vw_sets
                WHERE set_id = ?
            """, set_id)

            row = cursor.fetchone()

            if row is None:
                return func.HttpResponse(
                    json.dumps({
                        "error": "Set not found",
                        "set_id": set_id
                    }, ensure_ascii=False),
                    status_code=404,
                    mimetype="application/json"
                )

            columns = [column[0] for column in cursor.description]
            item = dict(zip(columns, row))

            if item["set_create_date"] is not None:
                item["set_create_date"] = item["set_create_date"].isoformat()

            if item["set_update_date"] is not None:
                item["set_update_date"] = item["set_update_date"].isoformat()

            return func.HttpResponse(
                json.dumps(item, ensure_ascii=False),
                status_code=200,
                mimetype="application/json"
            )

    except Exception as e:
        logging.exception("GET /api/sets/{set_id} failed")

        return func.HttpResponse(
            json.dumps({
                "error": "Database error",
                "message": str(e)
            }, ensure_ascii=False),
            status_code=500,
            mimetype="application/json"
        )
    
@app.route(route="sets/{set_id}/items", methods=["GET"])
def get_set_items(req: func.HttpRequest) -> func.HttpResponse:
    logging.info("GET /api/sets/{set_id}/items")

    if not check_api_key(req):
        return func.HttpResponse(
            json.dumps({"error": "Unauthorized"}),
            status_code=401,
            mimetype="application/json"
        )


    set_id = req.route_params.get("set_id")

    if not set_id:
        return func.HttpResponse(
            json.dumps({
                "error": "Missing set_id"
            }, ensure_ascii=False),
            status_code=400,
            mimetype="application/json"
        )

    try:
        set_id = int(set_id)
    except ValueError:
        return func.HttpResponse(
            json.dumps({
                "error": "Invalid set_id"
            }, ensure_ascii=False),
            status_code=400,
            mimetype="application/json"
        )

    try:
        connection_string = os.environ["SQL_CONNECTION_STRING"]

        with pyodbc.connect(connection_string, timeout=10) as conn:
            cursor = conn.cursor()

            cursor.execute(
                "SELECT 1 FROM vw_sets WHERE set_id = ?",
                set_id
            )

            if cursor.fetchone() is None:
                return func.HttpResponse(
                    json.dumps({
                        "error": "Set not found",
                        "set_id": set_id
                    }, ensure_ascii=False),
                    status_code=404,
                    mimetype="application/json"
                )

            cursor.execute(
                "EXEC dbo.sp_get_set_json @set_id = ?",
                set_id
            )

            row = cursor.fetchone()

            json_result = row[0]

            return func.HttpResponse(
                json_result,
                status_code=200,
                mimetype="application/json"
            )

    except Exception as e:
        logging.exception("GET /api/sets/{set_id}/items failed")

        return func.HttpResponse(
            json.dumps({
                "error": "Database error",
                "message": str(e)
            }, ensure_ascii=False),
            status_code=500,
            mimetype="application/json"
        )

@app.route(route="sets", methods=["POST"])
def save_set(req: func.HttpRequest) -> func.HttpResponse:
    logging.info("POST /api/sets")

    if not check_api_key(req):
        return func.HttpResponse(
            json.dumps({"error": "Unauthorized"}),
            status_code=401,
            mimetype="application/json"
        )

    # =========================================================
    # PARAMETERS
    # =========================================================

    user_id = req.params.get("user_id")

    if not user_id:
        return func.HttpResponse(
            json.dumps({
                "error": "Missing user_id"
            }, ensure_ascii=False),
            status_code=400,
            mimetype="application/json"
        )

    try:
        user_id = int(user_id)
    except ValueError:
        return func.HttpResponse(
            json.dumps({
                "error": "Invalid user_id"
            }, ensure_ascii=False),
            status_code=400,
            mimetype="application/json"
        )


    # =========================================================
    # JSON BODY
    # =========================================================

    try:
        body = req.get_json()
    except ValueError:
        return func.HttpResponse(
            json.dumps({
                "error": "Invalid JSON"
            }, ensure_ascii=False),
            status_code=400,
            mimetype="application/json"
        )

    # Проверяем, что это объект JSON
    if not isinstance(body, dict):
        return func.HttpResponse(
            json.dumps({
                "error": "JSON body must be an object"
            }, ensure_ascii=False),
            status_code=400,
            mimetype="application/json"
        )

    # =========================================================
    # DATABASE
    # =========================================================

    try:
        connection_string = os.environ["SQL_CONNECTION_STRING"]

        with pyodbc.connect(connection_string, timeout=10) as conn:
            cursor = conn.cursor()

            json_text = json.dumps(
                body,
                ensure_ascii=False
            )

            cursor.execute(
                """
                EXEC dbo.sp_save_set_json
                    @user_id = ?,
                    @json = ?
                """,
                user_id,
                json_text
            )

            row = cursor.fetchone()

            if row is None:
                return func.HttpResponse(
                    json.dumps({
                        "error": "Set was not saved"
                    }, ensure_ascii=False),
                    status_code=500,
                    mimetype="application/json"
                )

            new_set_id = row[0]

            return func.HttpResponse(
                json.dumps({
                    "set_id": new_set_id
                }, ensure_ascii=False),
                status_code=201,
                mimetype="application/json"
            )

    except pyodbc.Error as e:
        logging.exception("POST /api/sets database error")

        error_message = str(e)

        # =========================================================
        # STORED PROCEDURE ERRORS
        # =========================================================

        if "(50002)" in error_message:
            return func.HttpResponse(
                json.dumps({
                    "error": "User not found",
                    "user_id": user_id
                }, ensure_ascii=False),
                status_code=404,
                mimetype="application/json"
            )

        if "(50003)" in error_message:
            return func.HttpResponse(
                json.dumps({
                    "error": "Language level not found",
                    "language_level": body.get("language_level")
                }, ensure_ascii=False),
                status_code=404,
                mimetype="application/json"
            )

        if "(50004)" in error_message:
            return func.HttpResponse(
                json.dumps({
                    "error": "Phrase not found"
                }, ensure_ascii=False),
                status_code=400,
                mimetype="application/json"
            )

        if "(50005)" in error_message:
            return func.HttpResponse(
                json.dumps({
                    "error": "Phrase locale not found"
                }, ensure_ascii=False),
                status_code=400,
                mimetype="application/json"
            )

        if "(50006)" in error_message:
            return func.HttpResponse(
                json.dumps({
                    "error": "Phrase voice not found"
                }, ensure_ascii=False),
                status_code=400,
                mimetype="application/json"
            )

        if "(50007)" in error_message:
            return func.HttpResponse(
                json.dumps({
                    "error": "Translation locale not found"
                }, ensure_ascii=False),
                status_code=400,
                mimetype="application/json"
            )

        if "(50008)" in error_message:
            return func.HttpResponse(
                json.dumps({
                    "error": "Translation voice not found"
                }, ensure_ascii=False),
                status_code=400,
                mimetype="application/json"
            )

        # =========================================================
        # UNKNOWN DATABASE ERROR
        # =========================================================

        return func.HttpResponse(
            json.dumps({
                "error": "Database error",
                "message": error_message
            }, ensure_ascii=False),
            status_code=500,
            mimetype="application/json"
        )

    except Exception as e:
        logging.exception("POST /api/sets failed")

        return func.HttpResponse(
            json.dumps({
                "error": "Internal server error",
                "message": str(e)
            }, ensure_ascii=False),
            status_code=500,
            mimetype="application/json"
        )

@app.route(route="sets/{set_id}", methods=["PUT"])
def update_set(req: func.HttpRequest) -> func.HttpResponse:
    logging.info("PUT /api/sets/{set_id}")

    # =========================================================
    # API KEY
    # =========================================================

    if not check_api_key(req):
        return func.HttpResponse(
            json.dumps({
                "error": "Unauthorized"
            }, ensure_ascii=False),
            status_code=401,
            mimetype="application/json"
        )

    # =========================================================
    # SET ID
    # =========================================================

    set_id = req.route_params.get("set_id")

    if not set_id:
        return func.HttpResponse(
            json.dumps({
                "error": "Missing set_id"
            }, ensure_ascii=False),
            status_code=400,
            mimetype="application/json"
        )

    try:
        set_id = int(set_id)
    except ValueError:
        return func.HttpResponse(
            json.dumps({
                "error": "Invalid set_id"
            }, ensure_ascii=False),
            status_code=400,
            mimetype="application/json"
        )

    # =========================================================
    # JSON BODY
    # =========================================================

    try:
        body = req.get_json()

    except ValueError:
        return func.HttpResponse(
            json.dumps({
                "error": "Invalid JSON"
            }, ensure_ascii=False),
            status_code=400,
            mimetype="application/json"
        )

    if not isinstance(body, dict):
        return func.HttpResponse(
            json.dumps({
                "error": "JSON body must be an object"
            }, ensure_ascii=False),
            status_code=400,
            mimetype="application/json"
        )

    # =========================================================
    # PARAMETERS
    # =========================================================

    set_name = body.get("set_name")
    set_description = body.get("set_description")

    if not set_name:
        return func.HttpResponse(
            json.dumps({
                "error": "Missing set_name"
            }, ensure_ascii=False),
            status_code=400,
            mimetype="application/json"
        )

    # =========================================================
    # DATABASE
    # =========================================================

    try:
        connection_string = os.environ["SQL_CONNECTION_STRING"]

        with pyodbc.connect(
            connection_string,
            timeout=10
        ) as conn:

            cursor = conn.cursor()

            cursor.execute(
                """
                EXEC dbo.sp_update_set
                    @se_id = ?,
                    @se_name = ?,
                    @se_description = ?
                """,
                set_id,
                set_name,
                set_description
            )

            row = cursor.fetchone()

            if row is None:
                return func.HttpResponse(
                    json.dumps({
                        "error": "Set was not updated"
                    }, ensure_ascii=False),
                    status_code=500,
                    mimetype="application/json"
                )

            columns = [
                column[0]
                for column in cursor.description
            ]

            updated_set = dict(
                zip(columns, row)
            )

            # datetime2 → JSON string

            if updated_set["se_update_date"] is not None:
                updated_set["se_update_date"] = (
                    updated_set["se_update_date"].isoformat()
                )

            return func.HttpResponse(
                json.dumps({
                    "set_id": updated_set["se_id"],
                    "set_name": updated_set["se_name"],
                    "set_description": updated_set["se_description"],
                    "set_update_date": updated_set["se_update_date"]
                }, ensure_ascii=False),
                status_code=200,
                mimetype="application/json"
            )

    except pyodbc.Error as e:

        logging.exception(
            "PUT /api/sets/{set_id} database error"
        )

        error_message = str(e)

        # =====================================================
        # SET NOT FOUND
        # =====================================================

        if "(50001)" in error_message:
            return func.HttpResponse(
                json.dumps({
                    "error": "Set not found",
                    "set_id": set_id
                }, ensure_ascii=False),
                status_code=404,
                mimetype="application/json"
            )

        # =====================================================
        # UNKNOWN DATABASE ERROR
        # =====================================================

        return func.HttpResponse(
            json.dumps({
                "error": "Database error",
                "message": error_message
            }, ensure_ascii=False),
            status_code=500,
            mimetype="application/json"
        )

    except Exception as e:

        logging.exception(
            "PUT /api/sets/{set_id} failed"
        )

        return func.HttpResponse(
            json.dumps({
                "error": "Internal server error",
                "message": str(e)
            }, ensure_ascii=False),
            status_code=500,
            mimetype="application/json"
        )

@app.route(route="sets/{set_id}", methods=["DELETE"])
def delete_set(req: func.HttpRequest) -> func.HttpResponse:
    logging.info("DELETE /api/sets/{set_id}")

    # =========================================================
    # API KEY
    # =========================================================

    if not check_api_key(req):
        return func.HttpResponse(
            json.dumps({
                "error": "Unauthorized"
            }, ensure_ascii=False),
            status_code=401,
            mimetype="application/json"
        )

    # =========================================================
    # SET ID
    # =========================================================

    set_id = req.route_params.get("set_id")

    if not set_id:
        return func.HttpResponse(
            json.dumps({
                "error": "Missing set_id"
            }, ensure_ascii=False),
            status_code=400,
            mimetype="application/json"
        )

    try:
        set_id = int(set_id)
    except ValueError:
        return func.HttpResponse(
            json.dumps({
                "error": "Invalid set_id"
            }, ensure_ascii=False),
            status_code=400,
            mimetype="application/json"
        )

    # =========================================================
    # DATABASE
    # =========================================================

    try:
        connection_string = os.environ["SQL_CONNECTION_STRING"]

        with pyodbc.connect(
            connection_string,
            timeout=10
        ) as conn:

            cursor = conn.cursor()

            cursor.execute(
                """
                EXEC dbo.sp_delete_set
                    @se_id = ?
                """,
                set_id
            )

            row = cursor.fetchone()

            if row is None:
                return func.HttpResponse(
                    json.dumps({
                        "error": "Set was not deleted"
                    }, ensure_ascii=False),
                    status_code=500,
                    mimetype="application/json"
                )

            columns = [
                column[0]
                for column in cursor.description
            ]

            deleted_set = dict(
                zip(columns, row)
            )

            return func.HttpResponse(
                json.dumps({
                    "set_id": deleted_set["se_id"],
                    "deleted": True
                }, ensure_ascii=False),
                status_code=200,
                mimetype="application/json"
            )

    except pyodbc.Error as e:

        logging.exception(
            "DELETE /api/sets/{set_id} database error"
        )

        error_message = str(e)

        # =====================================================
        # SET NOT FOUND
        # =====================================================

        if "(50001)" in error_message:
            return func.HttpResponse(
                json.dumps({
                    "error": "Set not found",
                    "set_id": set_id
                }, ensure_ascii=False),
                status_code=404,
                mimetype="application/json"
            )

        # =====================================================
        # UNKNOWN DATABASE ERROR
        # =====================================================

        return func.HttpResponse(
            json.dumps({
                "error": "Database error",
                "message": error_message
            }, ensure_ascii=False),
            status_code=500,
            mimetype="application/json"
        )

    except Exception as e:

        logging.exception(
            "DELETE /api/sets/{set_id} failed"
        )

        return func.HttpResponse(
            json.dumps({
                "error": "Internal server error",
                "message": str(e)
            }, ensure_ascii=False),
            status_code=500,
            mimetype="application/json"
        )

@app.route(
    route="sets/{set_id}/mobile-audio/start",
    methods=["POST"]
)
def start_mobile_audio_preparation(
    req: func.HttpRequest
) -> func.HttpResponse:
    logging.info("POST /api/sets/{set_id}/mobile-audio/start")

    # Проверка API-ключа
    if not check_api_key(req):
        return func.HttpResponse(
            json.dumps({"error": "Unauthorized"}),
            status_code=401,
            mimetype="application/json"
        )

    # Получение set_id из URL
    set_id = req.route_params.get("set_id")

    try:
        set_id = int(set_id)
    except (TypeError, ValueError):
        return func.HttpResponse(
            json.dumps({
                "error": "Invalid set_id"
            }, ensure_ascii=False),
            status_code=400,
            mimetype="application/json"
        )

    try:
        connection_string = os.environ["SQL_CONNECTION_STRING"]

        with pyodbc.connect(
            connection_string,
            timeout=10
        ) as conn:
            cursor = conn.cursor()

            # Проверяем, что набор существует и активен
            cursor.execute(
                """
                SELECT 1
                FROM dbo.sets
                WHERE se_id = ?
                  AND se_active = 1
                """,
                set_id
            )

            if cursor.fetchone() is None:
                return func.HttpResponse(
                    json.dumps({
                        "error": "Set not found or inactive",
                        "set_id": set_id
                    }, ensure_ascii=False),
                    status_code=404,
                    mimetype="application/json"
                )

            # Сбрасываем отметку готовности
            cursor.execute(
                """
                UPDATE dbo.sets
                SET se_mobile_audio_ready_at = NULL
                WHERE se_id = ?
                  AND se_active = 1
                """,
                set_id
            )

        return func.HttpResponse(
            json.dumps({
                "set_id": set_id,
                "message": "Mobile audio preparation started"
            }, ensure_ascii=False),
            status_code=200,
            mimetype="application/json"
        )

    except Exception:
        logging.exception(
            "POST /api/sets/{set_id}/mobile-audio/start failed"
        )

        return func.HttpResponse(
            json.dumps({
                "error": "Database error"
            }, ensure_ascii=False),
            status_code=500,
            mimetype="application/json"
        )

@app.route(
    route="sets/{set_id}/mobile-audio/items",
    methods=["GET"]
)
def get_set_mobile_audio_items(
    req: func.HttpRequest
) -> func.HttpResponse:
    logging.info(
        "GET /api/sets/{set_id}/mobile-audio/items"
    )

    if not check_api_key(req):
        return func.HttpResponse(
            json.dumps({"error": "Unauthorized"}),
            status_code=401,
            mimetype="application/json"
        )

    set_id = req.route_params.get("set_id")

    try:
        set_id = int(set_id)
    except (TypeError, ValueError):
        return func.HttpResponse(
            json.dumps({"error": "Invalid set_id"}),
            status_code=400,
            mimetype="application/json"
        )

    try:
        connection_string = os.environ["SQL_CONNECTION_STRING"]

        with pyodbc.connect(
            connection_string,
            timeout=10
        ) as conn:
            cursor = conn.cursor()

            # Проверяем, что набор доступен пользователю.
            cursor.execute(
                """
                SELECT 1
                FROM vw_sets
                WHERE set_id = ?
                """,
                set_id
            )

            if cursor.fetchone() is None:
                return func.HttpResponse(
                    json.dumps({
                        "error": "Set not found or access denied",
                        "set_id": set_id
                    }, ensure_ascii=False),
                    status_code=404,
                    mimetype="application/json"
                )

            # Получаем данные для подготовки мобильного аудио.
            cursor.execute(
                """
                EXEC dbo.sp_get_set_mobile_audio_json
                    @set_id = ?
                """,
                set_id
            )

            row = cursor.fetchone()

            if row is None or row[0] is None:
                raise RuntimeError(
                    "Mobile audio JSON was not returned"
                )

            json_result = row[0]

        return func.HttpResponse(
            json_result,
            status_code=200,
            mimetype="application/json"
        )

    except Exception:
        logging.exception(
            "GET /api/sets/{set_id}/mobile-audio/items failed"
        )

        return func.HttpResponse(
            json.dumps({"error": "Database error"}),
            status_code=500,
            mimetype="application/json"
        )

@app.route(
    route="sets/{set_id}/items/{si_id}/mobile-audio",
    methods=["PUT"]
)
def upload_mobile_audio(
    req: func.HttpRequest
) -> func.HttpResponse:
    logging.info(
        "PUT /api/sets/{set_id}/items/{si_id}/mobile-audio"
    )

    if not check_api_key(req):
        return func.HttpResponse(
            json.dumps({"error": "Unauthorized"}),
            status_code=401,
            mimetype="application/json"
        )

    try:
        set_id = int(req.route_params.get("set_id"))
        si_id = int(req.route_params.get("si_id"))
    except (TypeError, ValueError):
        return func.HttpResponse(
            json.dumps({"error": "Invalid set_id or si_id"}),
            status_code=400,
            mimetype="application/json"
        )

    phrase_file = req.files.get("phrase_audio")
    translate_file = req.files.get("translate_audio")

    if phrase_file is None:
        return func.HttpResponse(
            json.dumps({
                "error": "phrase_audio is required"
            }),
            status_code=400,
            mimetype="application/json"
        )

    try:
        phrase_audio = phrase_file.read()
        translate_audio = (
            translate_file.read()
            if translate_file is not None
            else None
        )

        if not phrase_audio:
            return func.HttpResponse(
                json.dumps({
                    "error": "phrase_audio is empty"
                }),
                status_code=400,
                mimetype="application/json"
            )

        connection_string = os.environ["SQL_CONNECTION_STRING"]

        with pyodbc.connect(
            connection_string,
            timeout=10
        ) as conn:
            cursor = conn.cursor()

            # Проверяем доступ к набору.
            cursor.execute(
                """
                SELECT 1
                FROM vw_sets
                WHERE set_id = ?
                """,
                set_id
            )

            if cursor.fetchone() is None:
                return func.HttpResponse(
                    json.dumps({
                        "error": "Set not found or access denied",
                        "set_id": set_id
                    }, ensure_ascii=False),
                    status_code=404,
                    mimetype="application/json"
                )

            # Обновляем только указанный элемент этого набора.
            cursor.execute(
                """
                UPDATE dbo.set_items
                SET
                    si_mobile_phrase_audio = ?,
                    si_mobile_translate_audio = ?
                WHERE si_id = ?
                  AND si_set = ?
                """,
                pyodbc.Binary(phrase_audio),
                (
                    pyodbc.Binary(translate_audio)
                    if translate_audio is not None
                    else None
                ),
                si_id,
                set_id
            )

            if cursor.rowcount == 0:
                return func.HttpResponse(
                    json.dumps({
                        "error": "Set item not found",
                        "set_id": set_id,
                        "si_id": si_id
                    }, ensure_ascii=False),
                    status_code=404,
                    mimetype="application/json"
                )

        return func.HttpResponse(
            json.dumps({
                "set_id": set_id,
                "si_id": si_id,
                "message": "Mobile audio saved"
            }, ensure_ascii=False),
            status_code=200,
            mimetype="application/json"
        )

    except Exception:
        logging.exception(
            "PUT /api/sets/{set_id}/items/{si_id}/mobile-audio failed"
        )

        return func.HttpResponse(
            json.dumps({"error": "Database error"}),
            status_code=500,
            mimetype="application/json"
        )



@app.route(
    route="sets/{set_id}/items/{si_id}/mobile-audio/{audio_type}",
    methods=["GET"]
)
def download_mobile_audio(
    req: func.HttpRequest
) -> func.HttpResponse:
    """Download phrase or translation MP3 for one set item."""

    logging.info(
        "GET /api/sets/{set_id}/items/{si_id}/mobile-audio/{audio_type}"
    )

    if not check_api_key(req):
        return func.HttpResponse(
            json.dumps({"error": "Unauthorized"}),
            status_code=401,
            mimetype="application/json"
        )

    try:
        set_id = int(req.route_params.get("set_id"))
        si_id = int(req.route_params.get("si_id"))
    except (TypeError, ValueError):
        return func.HttpResponse(
            json.dumps({
                "error": "Invalid set_id or si_id"
            }, ensure_ascii=False),
            status_code=400,
            mimetype="application/json"
        )

    audio_type = req.route_params.get("audio_type")

    audio_columns = {
        "phrase": "si_mobile_phrase_audio",
        "translate": "si_mobile_translate_audio"
    }

    audio_column = audio_columns.get(audio_type)

    if audio_column is None:
        return func.HttpResponse(
            json.dumps({
                "error": "Invalid audio_type",
                "allowed_values": ["phrase", "translate"]
            }, ensure_ascii=False),
            status_code=400,
            mimetype="application/json"
        )

    try:
        connection_string = os.environ["SQL_CONNECTION_STRING"]

        with pyodbc.connect(
            connection_string,
            timeout=10
        ) as conn:
            cursor = conn.cursor()

            # Проверяем принадлежность элемента указанному набору.
            # Имя столбца берётся только из audio_columns выше.
            query = f"""
                SELECT {audio_column}
                FROM dbo.set_items
                WHERE si_id = ?
                  AND si_set = ?
            """

            cursor.execute(query, si_id, set_id)
            row = cursor.fetchone()

            if row is None:
                return func.HttpResponse(
                    json.dumps({
                        "error": "Set item not found",
                        "set_id": set_id,
                        "si_id": si_id
                    }, ensure_ascii=False),
                    status_code=404,
                    mimetype="application/json"
                )

            audio_data = row[0]

            if audio_data is None or len(audio_data) == 0:
                return func.HttpResponse(
                    json.dumps({
                        "error": "Audio not found",
                        "set_id": set_id,
                        "si_id": si_id,
                        "audio_type": audio_type
                    }, ensure_ascii=False),
                    status_code=404,
                    mimetype="application/json"
                )

            # pyodbc может вернуть bytes или memoryview.
            audio_bytes = bytes(audio_data)

        return func.HttpResponse(
            body=audio_bytes,
            status_code=200,
            mimetype="audio/mpeg",
            headers={
                "Content-Disposition":
                    f'attachment; filename="{si_id}_{audio_type}.mp3"',
                "Cache-Control": "private, no-store"
            }
        )

    except Exception:
        logging.exception(
            "GET mobile audio download failed: set_id=%s, si_id=%s",
            set_id,
            si_id
        )

        return func.HttpResponse(
            json.dumps({"error": "Database error"}),
            status_code=500,
            mimetype="application/json"
        )

@app.route(
    route="sets/{set_id}/mobile-audio/finish",
    methods=["POST"]
)
def finish_mobile_audio_preparation(
    req: func.HttpRequest
) -> func.HttpResponse:
    logging.info(
        "POST /api/sets/{set_id}/mobile-audio/finish"
    )

    if not check_api_key(req):
        return func.HttpResponse(
            json.dumps({"error": "Unauthorized"}),
            status_code=401,
            mimetype="application/json"
        )

    set_id = req.route_params.get("set_id")

    try:
        set_id = int(set_id)
    except (TypeError, ValueError):
        return func.HttpResponse(
            json.dumps({"error": "Invalid set_id"}),
            status_code=400,
            mimetype="application/json"
        )

    try:
        connection_string = os.environ["SQL_CONNECTION_STRING"]

        with pyodbc.connect(
            connection_string,
            timeout=10
        ) as conn:
            cursor = conn.cursor()

            # Проверяем доступ к набору.
            cursor.execute(
                """
                SELECT 1
                FROM vw_sets
                WHERE set_id = ?
                """,
                set_id
            )

            if cursor.fetchone() is None:
                return func.HttpResponse(
                    json.dumps({
                        "error": "Set not found or access denied",
                        "set_id": set_id
                    }, ensure_ascii=False),
                    status_code=404,
                    mimetype="application/json"
                )

            # Отмечаем завершение подготовки.
            cursor.execute(
                """
                UPDATE dbo.sets
                SET se_mobile_audio_ready_at = SYSDATETIME()
                WHERE se_id = ?
                  AND se_active = 1
                """,
                set_id
            )

            if cursor.rowcount == 0:
                return func.HttpResponse(
                    json.dumps({
                        "error": "Set not found or inactive",
                        "set_id": set_id
                    }, ensure_ascii=False),
                    status_code=404,
                    mimetype="application/json"
                )

        return func.HttpResponse(
            json.dumps({
                "set_id": set_id,
                "message": "Mobile audio preparation completed"
            }, ensure_ascii=False),
            status_code=200,
            mimetype="application/json"
        )

    except Exception:
        logging.exception(
            "POST /api/sets/{set_id}/mobile-audio/finish failed"
        )

        return func.HttpResponse(
            json.dumps({"error": "Database error"}),
            status_code=500,
            mimetype="application/json"
        )


@app.route(route="voice-test", methods=["POST"])
def voice_test(req: func.HttpRequest) -> func.HttpResponse:
    """Evaluate a spoken phrase using Azure Speech Pronunciation Assessment."""

    logging.info("POST /api/voice-test")

    if not check_api_key(req):
        return func.HttpResponse(
            json.dumps({
                "success": False,
                "error": {
                    "code": "unauthorized",
                    "message": "Unauthorized"
                }
            }, ensure_ascii=False),
            status_code=401,
            mimetype="application/json"
        )

    try:
        reference_text = req.form.get("reference_text")
        locale = req.form.get("locale")
        audio_file = req.files.get("audio")
        audio_bytes = audio_file.read() if audio_file is not None else None

        result = assess_pronunciation(
            reference_text=reference_text,
            locale=locale,
            audio_bytes=audio_bytes,
        )

        # Standard STT is supplementary: a failure here must not discard
        # a successful Pronunciation Assessment result.
        try:
            standard_result = recognize_speech(
                locale=locale,
                audio_bytes=audio_bytes,
            )
            result["standard_recognition"] = standard_result
            result["comparison"] = compare_transcription(
                reference_text=reference_text,
                recognition=standard_result,
            )
        except VoiceAssessmentError as error:
            logging.warning(
                "Supplementary standard recognition failed: code=%s",
                error.code,
            )
            result["standard_recognition"] = {
                "success": False,
                "error": {
                    "code": error.code,
                    "message": error.message,
                },
            }
            result["comparison"] = {
                "success": False,
                "error": {
                    "code": "standard_recognition_unavailable",
                    "message": "Text comparison could not be completed.",
                },
            }

        return func.HttpResponse(
            json.dumps(result, ensure_ascii=False),
            status_code=200,
            mimetype="application/json"
        )

    except VoiceAssessmentError as error:
        return func.HttpResponse(
            json.dumps({
                "success": False,
                "error": {
                    "code": error.code,
                    "message": error.message
                }
            }, ensure_ascii=False),
            status_code=error.status_code,
            mimetype="application/json"
        )

    except (ValueError, TypeError):
        logging.warning("POST /api/voice-test received invalid multipart data")
        return func.HttpResponse(
            json.dumps({
                "success": False,
                "error": {
                    "code": "invalid_multipart_request",
                    "message": (
                        "Request must be multipart/form-data with "
                        "reference_text, locale and audio fields."
                    )
                }
            }, ensure_ascii=False),
            status_code=400,
            mimetype="application/json"
        )

    except Exception:
        logging.exception("POST /api/voice-test failed")
        return func.HttpResponse(
            json.dumps({
                "success": False,
                "error": {
                    "code": "internal_error",
                    "message": "Internal server error."
                }
            }, ensure_ascii=False),
            status_code=500,
            mimetype="application/json"
        )



@app.route(route="voice-recognize", methods=["POST"])
def voice_recognize(req: func.HttpRequest) -> func.HttpResponse:
    """Transcribe audio using standard Azure Speech-to-Text without a reference."""
    logging.info("POST /api/voice-recognize")

    if not check_api_key(req):
        return func.HttpResponse(
            json.dumps({
                "success": False,
                "error": {
                    "code": "unauthorized",
                    "message": "Unauthorized"
                }
            }, ensure_ascii=False),
            status_code=401,
            mimetype="application/json"
        )

    try:
        locale = req.form.get("locale")
        audio_file = req.files.get("audio")
        audio_bytes = audio_file.read() if audio_file is not None else None

        result = recognize_speech(
            locale=locale,
            audio_bytes=audio_bytes,
        )

        return func.HttpResponse(
            json.dumps(result, ensure_ascii=False),
            status_code=200,
            mimetype="application/json"
        )

    except VoiceAssessmentError as error:
        return func.HttpResponse(
            json.dumps({
                "success": False,
                "error": {
                    "code": error.code,
                    "message": error.message
                }
            }, ensure_ascii=False),
            status_code=error.status_code,
            mimetype="application/json"
        )

    except (ValueError, TypeError):
        logging.warning(
            "POST /api/voice-recognize received invalid multipart data"
        )
        return func.HttpResponse(
            json.dumps({
                "success": False,
                "error": {
                    "code": "invalid_multipart_request",
                    "message": (
                        "Request must be multipart/form-data with "
                        "locale and audio fields."
                    )
                }
            }, ensure_ascii=False),
            status_code=400,
            mimetype="application/json"
        )

    except Exception:
        logging.exception("POST /api/voice-recognize failed")
        return func.HttpResponse(
            json.dumps({
                "success": False,
                "error": {
                    "code": "internal_error",
                    "message": "Internal server error."
                }
            }, ensure_ascii=False),
            status_code=500,
            mimetype="application/json"
        )
