import os
import pickle
import shutil
import pandas as pd
import gradio as gr
from config import PATHS
from secret_keys import *
from smolagents import CodeAgent, InferenceClientModel, tool
from sqlalchemy import (
    create_engine,
    MetaData,
    Table,
    Column,
    String,
    Integer,
    Float,
    insert,
    inspect,
    text,
    exc,
)
engine = create_engine("sqlite:///agentDB.db")
metadata_obj = MetaData()

def load_rows():
    """
       Loads dictionary with orient = list populated with column names as key and all the values in the column in a list.
           Args:
               None
           Returns:
               col_names (list): The list of column names.
               rows (list): list of rows containing values from each column.
               num_cols (int): Number of columns.
       """
    # load dict from pickle
    with open(PATHS.PKL_FILE_PATH, "rb") as f:
        sql_dict = pickle.load(f)

    # collect column names
    col_names = list(sql_dict.keys())
    num_cols = len(col_names)

    # Ensure the dictionary is not empty
    if not col_names:
        raise ValueError("The dictionary is empty.")

    # collect table rows from dict
    num_rows = len(sql_dict[col_names[0]])
    rows = []
    # Iterate through dict collecting each columns info as a row
    for i in range(num_rows):
        row = {}
        for col in col_names:
            value = sql_dict[col][i]
            row[col] = value
        rows.append(row)
    return col_names, rows, num_cols

def insert_rows(rows, table, engine = engine):
    """
       Insert rows into table.
           Args:
               rows (dict): Dictionary of rows to be inserted with column names as keys.
               table (sqlalchemy.Table): Table to be inserted.
               engine (sqlalchemy.engine): SQLAlchemy engine to be used.
           Returns:
               None
       """
    for row in rows:
        stmt = insert(table).values(**row)
        with engine.begin() as connection:
            connection.execute(stmt)


def create_dynamic_table(table_name, columns):
    """
       Creates an sql table dynamically.
           Args:
               table_name (String): name of the table
               columns (list): list of column names
           Returns:
               table: The table object.
       """
    table = Table(
        table_name,
        metadata_obj,
  Column('id', Integer, primary_key=True),
        *[Column(name, type_) for name, type_ in columns.items()],
        extend_existing=True
    )
    return table


def update_table(column_type):
    """
       Updates table with columns from gradio textbox. Calls load_rows() to read pkl file and get rows dict, column names, and number.
       Raises relevant error if number of data types does not match number of columns, if the user did not input a recognized data type, and if there are any errors inserting the rows.
           Args:
               column_type (String): The user inputed comma separated column data types.
           Returns:
                (String): Sucess message when no errors, the error that was raised when failure.
    """
    # load rows for the table
    col_names, rows, num_cols = load_rows()
    # split str into list of data types
    dataType_list = column_type.split(",")
    try:
        if len(dataType_list) != len(col_names):
            raise ValueError()
        for i in range(len(dataType_list)):
            match dataType_list[i].strip():
                case "String":
                    dataType_list[i] = String
                case "Integer":
                    dataType_list[i] = Integer
                case "Float":
                    dataType_list[i] = Float
            if dataType_list[i] != String and dataType_list[i] != Float and dataType_list[i] != Integer:
                raise TypeError()
    except TypeError as e:
        return f"A data type you entered was invalid."
    except ValueError as e:
        return f"{e}. Number of data types ({len(dataType_list)}) does not match number of columns ({len(col_names)})."

    # Dynamically create the columns dictionary
    columns = {
        col_name: dataType_list[i]  # Map column name to data type by index
        for i, col_name in enumerate(col_names)
    }
    len_cols = len(columns)
    dynamic_table = create_dynamic_table(PATHS.TABLE_NAME, columns)
    metadata_obj.create_all(engine)

    try:
        insert_rows(rows, dynamic_table)
    except exc.CompileError as e:
        return (f"{e}.")
    except exc.OperationalError as e:
        return (f"{e}. agentDB has already had it's schema defined.")
    return "Row insertion succesful"


def table_description():
   """
   Generates a description of the table to feed to agent prompt.
       Args:
           None
       Returns:
           table_description (String): The table's column names and their data types.
   """
   inspector = inspect(engine)
   try:
       columns_info = [(col["name"], col["type"]) for col in inspector.get_columns(PATHS.TABLE_NAME)]
       table_description = "Columns:\n" + "\n".join([f" - {name}: {col_type}" for name, col_type in columns_info])
   except exc.NoSuchTableError as e:
        return f"NoSuchTableError: {e}. The referenced table does not exist."
   return table_description

def table_check()-> str:
    """
    Verify the table exists. Returns a string which will say if the table exists or not.
        Args:
            None
        Returns:
            (String): A message containing table status.
    """
    try:
        inspector = inspect(engine)
        if inspector.has_table(PATHS.TABLE_NAME):
            return f"Table '{PATHS.TABLE_NAME}' exists."
        else:
            raise exc.NoSuchTableError()
    except exc.NoSuchTableError as e:
        return f"NoSuchTableError: {e} The referenced table does not exist."


@tool
def sql_engine(query: str) -> str:
    """
    Allows you to perform SQL queries on the table. Returns a string representation of the result.
        The Table is named agent_table.
        Args:
            query: The query to be performed on the table. This should always be correct SQL.
        """
    output = ""

    with engine.begin() as con:
        try:
            rows = con.execution_options(autocommit=True).execute(text(query))
            if not rows:
                return "No rows found, include the `RETURNING` keyword to ensure the result object always returns rows."
            else:
                for row in rows:
                    output += str(row) + "\n"
        except exc.SQLAlchemyError as e:
            return f"{e}. Include the `RETURNING` keyword to ensure the result object always returns rows."
    return output


def agent_setup():
    """
        Initialize the inference client, as well as the sql agent.
            Args:
                None
            Returns:
                sql_agent (Agent): The agent that will be used for inference.
            """
    sql_model = InferenceClientModel(
        api_key=NEBIUS_API_KEY,
        model_id="Qwen/Qwen3-235B-A22B",  # Qwen/Qwen3-4B
        provider="nebius",
    )
    # define SQL Agent
    sql_agent = CodeAgent(
        tools=[sql_engine],
        model=sql_model,
        max_steps=5,
    )
    return sql_agent

def run_prompt(prompt, history):
    """
        Initialize the inference client, as well as the sql agent.
            Args:
                prompt (String): The user's query to be fed to the agent.
                history (Any):
            Returns:
                sql_agent (Agent): The agent that will be used for inference.
            """
    table_descrip = table_description()
    table_status = table_check()
    if "NoSuchTableError" in table_status:
        return table_status + " Check the table has the expected name and it is consistent."
    return agent.run(prompt + f". Always wrap the result in relevant context and enforce the results object returning rows. Table description is as follows:{table_descrip}")


def vote(data: gr.LikeData):
    """
        Provide feedback to agent's response.
            Args:
                data (LikeData): carries information about the .like() event.
            Returns:
                None
            """
    if data.liked:
        print("You upvoted this response: " + data.value["value"])
    else:
        print("You downvoted this response: " + data.value["value"])


def process_file(fileobj):
    """
        Save file to temporary folder.
            Args:
                fileobj (Any): The uploaded file.
            Returns:
                None (calls csv_2_dict)
            """
    csv_path = PATHS.TEMP_PATH + os.path.basename(fileobj)
    # copy file to path
    shutil.copyfile(fileobj.name, csv_path)
    return csv_2_dict(csv_path)


def csv_2_dict(path):
    """
        Reads csv as a dataframe which is converted to a dictionary that is written to a pkl file in the temporary folder.
            Args:
                path (Any): The temporary file path.
            Returns:
                None
            """
    # read csv as dataframe then drop empties
    df = pd.read_csv(path)
    df_cleaned = df.dropna()
    # convert dataframe to a dictionary and save as pickle file
    table_data = df_cleaned.to_dict(orient='list')
    with open(PATHS.PKL_FILE_PATH, "wb") as f:
        pickle.dump(table_data, f)


def change_insert_mode(choice):
    """
        Drops table if user elects to upload a new table passes if no table to drop or user chooses to upload to existing table.
            Args:
                choice (Any): The name of the radio button the user has selected.
            Returns:
                None
            """
    table_status = table_check()
    if choice == "Upload New" and not "NoSuchTableError" in table_status:
        sql_engine(f"DROP TABLE {PATHS.TABLE_NAME};")
    else:
        pass

with gr.Blocks() as demo:
    with gr.Tab("Table Setup"):
        insert_mode = gr.Radio(["Upload New", "Upload to Existing"], label="Insertion Mode",
                               info="Warning selecting Upload New will immediately drop existing table, leaving unseleted will add to existing table.")
        insert_mode.input(fn=change_insert_mode, inputs=insert_mode, outputs=None)
        gr.Markdown("Next upload the csv:")
        gr.Interface(
            fn=process_file,
            inputs=[
                "file",
            ],
            outputs=None,
            flagging_mode="never"
        )
        column_type = gr.Textbox(label="Enter column data types (String, Integer, Float) as a comma seperated list:")
        column_type_message = gr.Textbox(label="Feedback:")
        col_type_button = gr.Button("Submit")
        col_type_button.click(update_table, inputs=column_type, outputs=[column_type_message, ])
    with gr.Tab("Text2SQL Agent"):
        chatbot = gr.Chatbot(type="messages", placeholder=f"<strong>Ask agent to perform a query.</strong>")
        chatbot.like(vote, None, None)
        gr.ChatInterface(fn=run_prompt, type="messages", chatbot=chatbot)

if __name__ == "__main__":
    # initialize agent once
    agent = agent_setup()

    demo.launch(debug=True)