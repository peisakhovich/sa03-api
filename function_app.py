import azure.functions as func
import logging
import os
import pyodbc
import os
import json

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