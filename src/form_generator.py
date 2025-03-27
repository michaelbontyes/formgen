"""
A script to generate OpenMRS 3 forms from a metadata file in Excel.
"""
import json
import os
import re
import time
import uuid
import openpyxl
import pandas as pd
import zipfile
from dotenv import load_dotenv

# Load the environment variables
load_dotenv()

# Load the configuration settings from config.json
with open('config.json', 'r', encoding='utf-8') as f:
    config = json.load(f)

# Extract the configuration settings
METADATA_FILE = os.getenv('METADATA_FILEPATH')
if not METADATA_FILE or METADATA_FILE.strip() == '':
    # If environment variable is not set, just initialize to empty
    METADATA_FILE = ''
    print(f"Warning: METADATA_FILEPATH environment variable not set. Please set it before using the generator functions.")

# Extract other configuration settings from config
TRANSLATION_SECTION_COLUMN = config.get('columns', {}).get('TRANSLATION_SECTION_COLUMN', 'Translation - Section')
TRANSLATION_QUESTION_COLUMN = config.get('columns', {}).get('TRANSLATION_QUESTION_COLUMN', 'Translation - Question')
TRANSLATION_TOOLTIP_COLUMN = config.get('columns', {}).get('TRANSLATION_TOOLTIP_COLUMN', 'Translation - Tooltip')
TRANSLATION_ANSWER_COLUMN = config.get('columns', {}).get('TRANSLATION_ANSWER_COLUMN', 'Translation')

# Since tooltip name is different in metadata, extract it form Configuration
TOOLTIP_COLUMN_NAME = config.get('columns', {}).get('TOOLTIP_COLUMN_NAME')

# Define option_sets as None initially
option_sets = None

# Initialize ALL_QUESTIONS_ANSWERS as an empty list
ALL_QUESTIONS_ANSWERS = []

def read_excel_skip_strikeout(filepath, sheet_name=0, header_row=1):
    """
    Reads an Excel sheet, skipping any row that has strikethrough formatting
    in any cell. Returns a Pandas DataFrame.

    :param filepath: Path to the Excel file
    :param sheet_name: Sheet name or index (0-based) to read
    :param header_row: Which row in Excel is the header (1-based index)
    :return: Pandas DataFrame with rows containing strikethrough removed
    """
    print(f"Reading sheet '{sheet_name}' from file: '{filepath}'")
    
    if not filepath or filepath.strip() == '':
        raise ValueError("Empty file path provided. Please check your METADATA_FILEPATH environment variable.")
        
    if not os.path.exists(filepath):
        raise FileNotFoundError(f"Excel file not found: '{filepath}'")
        
    try:
        # Load workbook (use data_only=True if you only need computed values)
        wb = openpyxl.load_workbook(filepath, data_only=True)
        ws = wb[sheet_name]

        # Convert 1-based to 0-based index for Python lists
        header_idx = header_row - 1

        # Grab all rows as openpyxl cell objects (not values_only=True,
        # so we can read formatting info).
        all_rows = list(ws.iter_rows())

        # Identify the header row cells and extract the column names
        header_cells = all_rows[header_idx]
        column_names = [cell.value for cell in header_cells]

        data = []
        # Iterate over the remaining rows after the header
        for row_idx in range(header_idx + 1, len(all_rows)):
            row_cells = all_rows[row_idx]
            row_has_strike = False
            row_values = []

            for cell in row_cells:
                # Check if the cell has a font and if that font uses strikethrough
                if sheet_name == 'OptionSets':
                    if cell.font and cell.font.strike:
                        row_has_strike = True
                        break  # No need to check other cells in this row
                else:
                    question_cell = row_cells[column_names.index('Question')]
                    if question_cell.font and question_cell.font.strike:
                        row_has_strike = True
                        break  # No need to check other cells in this row
                row_values.append(cell.value)

            if not row_has_strike:
                data.append(row_values)

        # Create a DataFrame from the filtered data
        df = pd.DataFrame(data, columns=column_names)
        return df
    except zipfile.BadZipFile:
        raise zipfile.BadZipFile("The Excel file appears to be corrupted. Please try re-saving it in .xlsx format.")
    except KeyError:
        raise KeyError(f"Sheet '{sheet_name}' not found in the Excel file.")
    except Exception as e:
        # Try using pandas directly as a fallback
        try:
            print(f"Attempting to read {sheet_name} with pandas directly using file: {filepath}")
            # Try with openpyxl engine first
            df = pd.read_excel(filepath, sheet_name=sheet_name, header=header_row-1, engine='openpyxl')
            print(f"Successfully read {sheet_name} with pandas using openpyxl engine.")
            return df
        except Exception as pandas_error_openpyxl:
            try:
                # Try with default engine as fallback (don't specify engine)
                print(f"Attempting with default engine...")
                df = pd.read_excel(filepath, sheet_name=sheet_name, header=header_row-1)
                print(f"Successfully read {sheet_name} with pandas using default engine.")
                return df
            except Exception as pandas_error_default:
                raise Exception(f"Error reading Excel file: {str(e)}. "
                               f"Pandas fallback with openpyxl failed: {str(pandas_error_openpyxl)}. "
                               f"Default engine fallback also failed: {str(pandas_error_default)}")

def initialize_option_sets(metadata_file=None):
    """
    Initialize option_sets from the metadata file
    
    Args:
        metadata_file (str, optional): Path to the metadata file. If None, uses the global METADATA_FILE.
    """
    global option_sets
    
    # Use the provided metadata_file if available, otherwise use the global METADATA_FILE
    file_to_use = metadata_file if metadata_file else METADATA_FILE
    
    if not file_to_use or not os.path.exists(file_to_use):
        raise FileNotFoundError(f"Metadata file not found: '{file_to_use}'")
        
    try:
        option_sets = read_excel_skip_strikeout(filepath=file_to_use, sheet_name='OptionSets', header_row=2)
    except Exception as e:
        # Try a direct pandas approach as fallback
        try:
            print(f"Attempting to read OptionSets with pandas directly using file: {file_to_use}")
            # Try with openpyxl engine first
            option_sets = pd.read_excel(file_to_use, sheet_name='OptionSets', header=1, engine='openpyxl')
            print("Successfully read OptionSets with pandas using openpyxl engine.")
        except Exception as pandas_error_openpyxl:
            try:
                # Try with default engine as fallback
                print(f"Attempting with default engine...")
                option_sets = pd.read_excel(file_to_use, sheet_name='OptionSets', header=1)
                print("Successfully read OptionSets with pandas using default engine.")
            except Exception as pandas_error_default:
                raise Exception(f"Failed to read OptionSets sheet: {str(e)}. "
                               f"Pandas fallback with openpyxl failed: {str(pandas_error_openpyxl)}. "
                               f"Default engine fallback also failed: {str(pandas_error_default)}")

# Function to fetch options for a given option set
def get_options(option_set_name):
    """
    Fetch options for a given option set name.

    Args:
        option_set_name (str): The name of the option set.

    Returns:
        list: A list of dictionaries containing option set details.
    """
    if option_sets is None:
        raise ValueError("Option sets not initialized. Call initialize_option_sets first.")
    return option_sets[option_sets['OptionSet name'] == option_set_name].to_dict(orient='records')

def find_question_concept_by_label(questions_answers, question_label):
    """
    Find question concept by label.
    
    Args:
        questions_answers (list): List of question answer dictionaries
        question_label (str): The label to search for
        
    Returns:
        str: The question ID if found, otherwise a generated ID
    """
    if not questions_answers:
        return manage_id(question_label)
        
    for question in questions_answers:
        if question.get('question_id') == manage_id(question_label):
            return question.get('question_id')
    return manage_id(question_label)

def find_answer_concept_by_label(questions_answers, question_id, answer_label):
    """
    Find answer concept by label.
    
    Args:
        questions_answers (list): List of question answer dictionaries
        question_id (str): The question ID to search for
        answer_label (str): The answer label to search for
        
    Returns:
        str: The answer concept if found, otherwise a generated ID
    """
    if not questions_answers:
        return manage_id(answer_label)
        
    for question in questions_answers:
        if question.get('question_id') == manage_id(question_id):
            for answer in question.get('questionOptions', {}).get('answers', []):
                if answer.get('label') == answer_label:
                    return answer.get('concept')
    return manage_id(answer_label)

def safe_json_loads(s):
    """
    Safe json loads.
    """
    try:
        return json.loads(s)
    except (ValueError, TypeError):
        return None

def manage_rendering(rendering):
    """
    Manage rendering options.
    """
    if rendering == 'radio':
        rendering = 'radio'
    elif rendering == 'multicheckbox':
        rendering = 'multiCheckbox'
    elif rendering == 'inlinemulticheckbox':
        rendering = 'multiCheckbox'
    elif rendering == 'boolean':
        rendering = 'radio'
    elif rendering == 'numeric':
        rendering = 'numeric'
    elif rendering == 'text':
        rendering = 'text'
    elif rendering == 'textarea':
        rendering = 'textarea'
    elif rendering == 'decimalnumber':
        rendering = 'number'
    return rendering

def format_label(original_label):
    """
    Format the label.
    """
    # Clean the label
    label = remove_prefixes(original_label)
    # Remove any other non-alphanumeric characters except spaces, (), -, _, /, ., <, > and +
    label = re.sub(r'[^a-zA-Z0-9\s\(\)\-_\/\.<>+]', '', label)
    # Remove leading ". " prefixes
    label = re.sub(r'^\.\s*', '', label)

    return label

def manage_label(original_label):
    """
    Manage labels.

    Args:
        original_label (str): The original label.

    Returns:
        str: The cleaned label.
    """
    # Format the label
    # label = format_label(original_label)

    return original_label

# Manage IDs
def manage_id(original_id, id_type="question", question_id="None", all_questions_answers=None):
    """
    Manage IDs.

    Args:
        original_id (str): The original ID.
        id_type (str, optional): The ID type. Defaults to "question".
        question_id (str, optional): The question ID. Defaults to "None".
        all_questions_answers (list, optional): A list of all questions and their answers.
        Defaults to None.

    Returns:
        str: The cleaned ID.
    """
    if all_questions_answers is None:
        all_questions_answers = []
    cleaned_id = remove_prefixes(original_id)
    cleaned_id = re.sub(r'\s*\(.*?\)', '', cleaned_id)
    # Replace "/" with "Or"
    cleaned_id = re.sub(r'/', ' Or ', cleaned_id)
    if not detect_range_prefixes(cleaned_id):
        # Replace "-" with a space
        cleaned_id = re.sub(r'-', ' ', cleaned_id)
        # Replace "_" with a space
        cleaned_id = re.sub(r'_', ' ', cleaned_id)
    # Replace "-"
    cleaned_id = re.sub(r'-', 'To', cleaned_id)
    # Replace "<"
    cleaned_id = re.sub(r'<', 'Less Than', cleaned_id)
    # Replace "<"
    cleaned_id = re.sub(r'>', 'More Than', cleaned_id)
    cleaned_id = camel_case(cleaned_id)
    # Replace '+' characters with 'plus'
    cleaned_id = re.sub(r'\+', 'Plus', cleaned_id)
    # Remove any other non-alphanumeric characters
    cleaned_id = re.sub(r'[^a-zA-Z0-9_-]', '', cleaned_id)
    # Remove leading and trailing underscores
    cleaned_id = re.sub(r'^_+|_+$', '', cleaned_id)
    # Replace multiple underscores with a single underscore
    cleaned_id = re.sub(r'_+', '_', cleaned_id)
    cleaned_id = cleaned_id[0].lower() + cleaned_id[1:]
    if id_type == "answer" and cleaned_id == 'other':
        cleaned_id = str(question_id)+str(cleaned_id.capitalize())
    if all_questions_answers is not None:
        duplicate_count = 1
        original_cleaned_id = cleaned_id
        while any(q['question_id'] == cleaned_id for q in all_questions_answers):
            cleaned_id = f"{original_cleaned_id}_{duplicate_count}"
            duplicate_count += 1
    return cleaned_id

def remove_prefixes(text):
    """
    Remove numerical prefixes from the beginning of the string.
    Examples of prefixes: "1. ", "1.1 ", "1.1.1 ", etc.

    Parameters:
    text (str): The input string from which to remove prefixes.

    Returns:
    str: The string with the prefixes removed.
    """
    if not detect_range_prefixes(text):
        # Convert text to string before using re.sub
        text = str(text)
        # Use re.sub to remove the matched prefix
        text = re.sub(r'^\d+(\.\d+)*\s*', '', text)
    return text

def detect_range_prefixes(text):
    """
    Detect ranges in the beginning of the string.
    """
    pattern = r"(\d+-\d+|\> \d+|< \d+|\d+ - \d+|\d+-\d+)"
    matches = re.findall(pattern, str(text))  # Convert text to string
    return bool(matches)

def camel_case(text):
    """
    Camel case a string.
    """
    words = text.split()
    # If text is empty, return UUID
    if not words or text == '%':
        return str(uuid.uuid4())
    # Convert the first word to lowercase and capitalize the rest of the words
    camel_case_text = words[0].lower()
    for word in words[1:]:
        camel_case_text += word.capitalize()
    return camel_case_text

def build_skip_logic_expression(expression: str, questions_answers) -> str:
    """
    Build a skip logic expression from an expression string.

    Args:
        expression (str): An expression string.

    Returns:
        str: A skip logic expression.
    """
    # Regex pattern to match the required parts
    pattern = r"\[([^\]]+)\]\s*(<>|!==|==)\s*'([^']*)'"
    uuid_pattern = r'[a-fA-F0-9]{8}-' \
                '[a-fA-F0-9]{4}-' \
                '[a-fA-F0-9]{4}-' \
                '[a-fA-F0-9]{4}-' \
                '[a-fA-F0-9]{12}|' \
                '[a-fA-F0-9]{32}'
    match = re.search(pattern, expression)

    if match:
        original_question_label, operator, original_cond_answer = match.groups()
        if operator == '<>':
            operator = '!=='
        elif operator != '!==':
            return 'Only conditional operator "different than" noted !== is supported'
        # Check if original_question_label is a 36 character UUID
        if re.match(uuid_pattern, original_question_label):
            question_id = original_question_label
        else:
            question_id = find_question_concept_by_label(questions_answers, original_question_label)
        # Check if original_cond_answer is a 36 character UUID
        if re.match(uuid_pattern, original_cond_answer):
            cond_answer = original_cond_answer
        else:
            cond_answer = find_answer_concept_by_label(
                questions_answers, original_question_label, original_cond_answer
                )
        return f"{question_id} {operator} '{cond_answer}'"

    return "Invalid expression format"


def should_render_workspace(question_rendering):
    """
    Check if a workspace should be rendered
    """
    # List of words to check against
    other_render_options = ["radio", "number", "text", "date", "time", "markdown", "select", "checkbox", "toggle", "multiCheckbox", "textarea", "numeric"]

    for word in other_render_options:
        if word in question_rendering:
            return False
    return True

def get_workspace_button_label(button_label):
    """
    Get the button name for the workspace being rendered.
    """
    if button_label == 'immunization-form-workspace':
        button_label = 'Capture patient immunizations'
    elif button_label == 'order-basket':
        button_label = 'Order medications'
    elif button_label == 'appointments-form-workspace':
        button_label = 'Set the next appointment date'
    elif button_label == 'patient-vitals-biometrics-form-workspace':
        button_label = 'Capture patient vitals'
    elif button_label == 'medications-form-workspace':
        button_label = 'Active medications'
    else :
        button_label = 'Open Workspace'
    return button_label

def add_translation(translations, label, translated_string):
    """
    Add a translation to the translations dictionary.
    """
    if translated_string is None:
        # LOG: Translation not present for the provided label
        pass
    if label in translations:
        if translations[label] != translated_string:
            # LOG: Different translations for same label: label
            pass
        else:
            return
    translations[label] = translated_string

def generate_question(row, columns, question_translations):
    """
    Generate a question JSON from a row of the OptionSets sheet.

    Args:
        row (pandas.Series): A row of the OptionSets sheet.
        columns (list): A list of column names in the OptionSets sheet.

    Returns:
        dict: A question JSON.
    """

    if row.isnull().all() or pd.isnull(row['Question']):
        return None  # Skip empty rows or rows with empty 'Question'

    # Manage values and default values
    original_question_label = (row['Label if different'] if 'Label if different' in columns and
                            pd.notnull(row['Label if different']) else row['Question'])

    question_label_translation = (
        row[TRANSLATION_QUESTION_COLUMN].replace('"', '').replace("'", '').replace('\\', '/') if TRANSLATION_QUESTION_COLUMN in columns and
                            pd.notnull(row[TRANSLATION_QUESTION_COLUMN]) else None
                            )

    question_label = manage_label(original_question_label)
    question_id = (row['Question ID'] if 'Question ID' in columns and
                        pd.notnull(row['Question ID']) else manage_id(original_question_label))

    original_question_info = (row[TOOLTIP_COLUMN_NAME] if TOOLTIP_COLUMN_NAME in columns and
                            pd.notnull(row[TOOLTIP_COLUMN_NAME]) else None )
    question_info = manage_label(original_question_info)

    question_concept_id = (row['External ID'] if 'External ID' in columns and
                        pd.notnull(row['External ID']) else question_id)

    question_datatype = (row['Datatype'].lower() if pd.notnull(row['Datatype']) else 'radio')

    validation_format = (row['Validation (format)'] if 'Validation (format)' in columns and
                        pd.notnull(row['Validation (format)']) else '')

    question_required = (str(row['Mandatory']).lower() == 'true' if 'Mandatory' in columns and
                        pd.notnull(row['Mandatory']) else False)

    question_rendering_value = (row['Rendering'].lower() if pd.notnull(row['Rendering']) else 'text')

    question_rendering = manage_rendering(question_rendering_value)

    # Build the question JSON
    question = {
        "id": question_id,
        "label": question_label,
        "type": "obs",
        "required": question_required,
    }

    question_options = {
        "rendering": question_rendering,
        "concept": question_concept_id
    }

    # Add min/max values if rendering is numeric/number
    if question_rendering in ['numeric', 'number']:
        if 'Lower limit' in columns and pd.notnull(row['Lower limit']):
            question_options['min'] = row['Lower limit']
        if 'Upper limit' in columns and pd.notnull(row['Upper limit']):
            question_options['max'] = row['Upper limit']

    if should_render_workspace(question_rendering):
        workspace_button_label = get_workspace_button_label(question_rendering)
        question.pop('type')
        question_options = {
            "rendering": "workspace-launcher",
            "buttonLabel": workspace_button_label,
            "workspaceName": question_rendering
        }

    question['questionOptions'] = question_options

    # If question_rendering_value == 'markdown' then append key 'value' with the value similar to the label and change the type key to 'markdown'
    if question_rendering_value == 'markdown':
        question['value'] = [f"## {question_label}"]
        question['type'] = 'markdown'
        question['questionOptions'].pop('concept')

    # If question_rendering_value == 'inlineMultiCheckbox' then append a line in question before 'questionOptions' with '"inlineMultiCheckbox": true,'
    if question_rendering_value == 'inlinemulticheckbox':
        question['inlineMultiCheckbox'] = True

    if question_rendering_value == 'decimalnumber':
        question['disallowDecimals'] = False

    add_translation(question_translations, question_label, question_label_translation)

    question_validators = safe_json_loads(validation_format)
    if pd.notnull(question_validators):
        question['validators'] = question_validators

    if 'Default value' in columns and pd.notnull(row['Default value']):
        question['default'] = row['Default value']

    if TOOLTIP_COLUMN_NAME in columns and pd.notnull(row[TOOLTIP_COLUMN_NAME]):
        question['questionInfo'] = question_info
        question_info_translation = (
            row[TRANSLATION_TOOLTIP_COLUMN].replace('"', '').replace("'", '').replace('\\', '/') 
                if (
                    TRANSLATION_TOOLTIP_COLUMN in columns and
                    pd.notnull(row[TRANSLATION_TOOLTIP_COLUMN])
                ) else None
        )
        add_translation(question_translations, question_info, question_info_translation)

    if 'Calculation' in columns and pd.notnull(row['Calculation']):
        question['questionOptions']['calculate'] = {"calculateExpression": row['Calculation']}

    if 'Skip logic' in columns and pd.notnull(row['Skip logic']):
        question['hide'] = {"hideWhenExpression": build_skip_logic_expression(
            row['Skip logic'], ALL_QUESTIONS_ANSWERS
            )}

    if 'OptionSet name' in columns and pd.notnull(row['OptionSet name']):
        options = get_options(row['OptionSet name'])
        question['questionOptions']['answers'] = []

        for opt in options:
            answer = {
                "label": manage_label(opt['Answers']),
                "concept": (manage_id(opt['Answers']) if opt['External ID'] == '#N/A' else
                    (opt['External ID'] if 'External ID' in columns and
                        pd.notnull(opt['External ID'])
                        else manage_id(opt['Answers'], id_type="answer",
                            question_id=question_id,
                            all_questions_answers=ALL_QUESTIONS_ANSWERS)))
            }
            question['questionOptions']['answers'].append(answer)
            # Manage Answer labels
            answer_label = manage_label(opt['Answers'])
            translated_answer_label = (row[TRANSLATION_ANSWER_COLUMN] if TRANSLATION_ANSWER_COLUMN in columns and
                            pd.notnull(row[TRANSLATION_ANSWER_COLUMN]) else None )
            add_translation(question_translations, answer_label, translated_answer_label)
            


        ALL_QUESTIONS_ANSWERS.append({
            "question_id": question['id'],
            "question_label": question['label'],
            "questionOptions": {
                "answers": question['questionOptions']['answers']
            }
        })

    # Pop answers key if answers array is empty
    if 'answers' in question['questionOptions'] and not question['questionOptions']['answers']:
        question['questionOptions'].pop('answers')

    # Rename the variable inside the 'with' statement
    with open('all_questions_answers.json', 'w', encoding='utf-8') as file:
        json.dump(ALL_QUESTIONS_ANSWERS, file, indent=2)

    return question

def generate_form(sheet_name, form_translations, metadata_file=None):
    """
    Generate a form JSON from a sheet of the OptionSets sheet.

    Args:
        sheet_name (str): The name of the sheet in the OptionSets sheet.
        form_translations (dict): Dictionary to store translations.
        metadata_file (str, optional): Path to the metadata file. If None, uses the global METADATA_FILE.

    Returns:
        dict: A form JSON.
    """
    # Reset the global ALL_QUESTIONS_ANSWERS list
    global ALL_QUESTIONS_ANSWERS
    ALL_QUESTIONS_ANSWERS = []
    
    form_data = {
        "name": sheet_name,
        "description": "MSF Form - "+sheet_name,
        "version": "1",
        "published": True,
        "uuid": "",
        "processor": "EncounterFormProcessor",
        "encounter": "Consultation",
        "retired": False,
        "referencedForms": [],
        "pages": []
    }

    # Use the provided metadata_file if available, otherwise use the global METADATA_FILE
    file_to_use = metadata_file if metadata_file else METADATA_FILE
    
    if not file_to_use or not os.path.exists(file_to_use):
        raise FileNotFoundError(f"Metadata file not found: '{file_to_use}'")

    try:
        # Adjust header to start from row 2 and keep Excel font formatting including strike out characters
        df = read_excel_skip_strikeout(filepath=file_to_use, sheet_name=sheet_name, header_row=2)
    except Exception as e:
        # Try a direct pandas approach as fallback
        try:
            print(f"Attempting to read {sheet_name} with pandas directly using file: {file_to_use}")
            # Try with openpyxl engine first
            df = pd.read_excel(file_to_use, sheet_name=sheet_name, header=1, engine='openpyxl')
            print(f"Successfully read {sheet_name} with pandas using openpyxl engine.")
        except Exception as pandas_error_openpyxl:
            try:
                # Try with default engine as fallback
                print(f"Attempting with default engine...")
                df = pd.read_excel(file_to_use, sheet_name=sheet_name, header=1)
                print(f"Successfully read {sheet_name} with pandas using default engine.")
            except Exception as pandas_error_default:
                raise Exception(f"Failed to read sheet {sheet_name}: {str(e)}. "
                               f"Pandas fallback with openpyxl failed: {str(pandas_error_openpyxl)}. "
                               f"Default engine fallback also failed: {str(pandas_error_default)}")

    columns = df.columns.tolist()

    # concept_ids is defined here, not inside the function
    concept_ids_set = set()

    pages = df['Page'].unique()

    # Keep track of total questions and answers
    count_total_questions = 0
    count_total_answers = 0

    for page in pages:
        page_df = df[df['Page'] == page]

        form_data["pages"].append({
            "label": f"{page}",
            "sections": []
        })

        for section in page_df['Section'].unique():
            section_df = page_df[page_df['Section'] == section]
            section_label = (
                section_df['Section'].iloc[0] if pd.notnull(section_df['Section'].iloc[0])
                            else '')

            # Add section label translations to form_translations
            section_label_translation = (
                section_df[TRANSLATION_SECTION_COLUMN].iloc[0].replace('"', '').replace("'", '').replace('\\', '/')
                if TRANSLATION_SECTION_COLUMN in columns and pd.notnull(section_df[TRANSLATION_SECTION_COLUMN].iloc[0])
                else None
            )
            form_translations[section_label] = section_label_translation

            questions = [generate_question(row, columns, form_translations)
                        for _, row in section_df.iterrows()
                        if not row.isnull().all() and pd.notnull(row['Question'])]

            questions = [q for q in questions if q is not None]

            count_total_questions += len(questions)
            count_total_answers += sum(
                len(q['questionOptions']['answers']) if 'answers' in q['questionOptions']
                else 0 for q in questions
                )

            form_data["pages"][-1]["sections"].append({
                "label": section_label,
                "isExpanded": False,
                "questions": questions
            })

    return form_data, concept_ids_set, count_total_questions, count_total_answers

def generate_translation_file(form_name, language, translations_list):
    """
    Generate a translation file JSON.

    Args:
        form_name (str): The name of the form.
        language (str): The language of the translations.
        translations (dict): A dictionary containing the translations.

    Returns:
        dict: A translation file JSON.
    """

    # Reorganize keys in translations_list alphabetically
    ordered_translations_list = {k: v for k, v in sorted(translations_list.items(), key=lambda item: item[0])}

    # Build the translation file JSON
    translation_file = {
        "uuid": "",
        "form": form_name,
        "description": f"{language.capitalize()} Translations for '{form_name}'",
        "language": language,
        "translations": ordered_translations_list
    }

    return translation_file

# Generate forms and save as JSON
OUTPUT_DIR = './generated_form_schemas'
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Load the data
all_concept_ids = set()
all_forms = []
TOTAL_QUESTIONS = 0
TOTAL_ANSWERS = 0

# Start the timer
start_time = time.time()

# The following code should be removed or commented out:
# for sheet in SHEETS:
#     translations_data = {}
#     form, concept_ids, total_questions, total_answers = generate_form(sheet, translations_data)
#     translations = generate_translation_file(sheet, 'ar', translations_data)
#     json_data = json.dumps(form, indent=2)
#     translations_json_data = json.dumps(translations, ensure_ascii=False, indent=2)
#     try:
#         json.loads(json_data)  # Validate JSON format
#         form_name_output = sheet.replace(" ", "_")
#         with open(os.path.join(OUTPUT_DIR, f"{form_name_output}.json"), 'w', encoding='utf-8') as f:
#             f.write(json_data)
#         print(f"Configuration file for form {sheet} generated successfully!")
#         json.loads(translations_json_data)  # Validate JSON format
#         translation_file_name_output = sheet.replace(" ", "_")
#         with open(os.path.join(OUTPUT_DIR, f"{translation_file_name_output}_translations_ar.json"), 'w', encoding='utf-8') as f:
#             f.write(translations_json_data)
#         print(f"Translation file for form {sheet} generated successfully!")
#         print()
#     except json.JSONDecodeError as e:
#         print(f"JSON format error in form generated from sheet {sheet}: {e}")
#         print(f"JSON format error in translations form generated from sheet {sheet}: {e}")
#     all_concept_ids.update(concept_ids)
#     all_forms.append(form)
#     TOTAL_QUESTIONS += total_questions
#     TOTAL_ANSWERS += total_answers

# # Count the number of forms generated
# FORMS_GENERATED = len(SHEETS)

# # End the timer
# end_time = time.time()

# # Calculate the total time taken
# total_time = end_time - start_time

# # Print the completion message with the number of forms generated
# print("Forms generation completed!")
# print(f"{FORMS_GENERATED} forms generated in {total_time:.2f} seconds")
# print(f"Total number of questions across all forms: {TOTAL_QUESTIONS}")
# print(f"Total number of answers across all forms: {TOTAL_ANSWERS}")
