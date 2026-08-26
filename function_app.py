import os
import json
import logging
import pyodbc
import azure.functions as func

app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)


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

    try:
        conn = pyodbc.connect(os.environ["SQL_CONNECTION_STRING"])
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
            ORDER BY user_id, set_index
        """)

        columns = [column[0] for column in cursor.description]

        rows = []
        for row in cursor.fetchall():
            item = dict(zip(columns, row))

            # datetime2 → строка JSON
            if item["set_create_date"] is not None:
                item["set_create_date"] = item["set_create_date"].isoformat()

            if item["set_update_date"] is not None:
                item["set_update_date"] = item["set_update_date"].isoformat()

            rows.append(item)

        cursor.close()
        conn.close()

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
    
@app.route(route="sets/{set_id}", methods=["GET"])
def get_set(req: func.HttpRequest) -> func.HttpResponse:
    logging.info("GET /api/sets/{set_id}")

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

    # =========================================================
    # PARAMETERS
    # =========================================================

    user_id = req.params.get("user_id")
    language_level_id = req.params.get("language_level_id")

    if not user_id:
        return func.HttpResponse(
            json.dumps({
                "error": "Missing user_id"
            }, ensure_ascii=False),
            status_code=400,
            mimetype="application/json"
        )

    if not language_level_id:
        return func.HttpResponse(
            json.dumps({
                "error": "Missing language_level_id"
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

    try:
        language_level_id = int(language_level_id)
    except ValueError:
        return func.HttpResponse(
            json.dumps({
                "error": "Invalid language_level_id"
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
                    @language_level_id = ?,
                    @json = ?
                """,
                user_id,
                language_level_id,
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
                    "language_level_id": language_level_id
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
