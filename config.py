import os

class PATHS:
    # get temp path from env
    TEMP_PATH = os.getenv('Temp')
    
    TABLE_NAME = "agent_table"
    
    PKL_FILE_PATH = TEMP_PATH + "/TABLE_DATA.pkl"

