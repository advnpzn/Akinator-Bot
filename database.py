from pprint import pprint
from typing import Any
from pymongo import MongoClient
from telegram import user
from config import AKI_MONGO_HOST
import itertools

my_client = MongoClient(host=AKI_MONGO_HOST)
my_db = my_client["aki-db"]


def addUser(user_id: int, first_name: str, last_name: str, user_name: str) -> None:
    """
    Adding the User to the database. If user already present in the database,
    it will check for any changes in the user_name, first_name, last_name and will update if true.
    """
    #"Users" Collection (Table).
    my_col = my_db["users"]
    #Finding if the user_id of the user is in the collection (Table), if found, assigning it to user variable.
    user = my_col.find_one({"user_id": user_id})
    #Checking if the user_id matches with the one from the Collection (Table).
    #If the user_id is not in the Collection (Table), the below statement adds the user to the Collection (Table).
    if user is None:
        my_dict = {
        "user_id": user_id,
        "first_name": first_name,
        "last_name": last_name,
        "user_name": user_name,
        "aki_lang": "en",
        "child_mode": 1,
        "total_guess": 0,
        "correct_guess": 0,
        "wrong_guess": 0,
        "unfinished_guess": 0,
        "total_questions": 0,
    }
        my_col.insert_one(my_dict)
    elif user["user_id"] == user_id:
        updateUser(user_id, first_name, last_name, user_name)

    
def totalUsers():
    my_col = my_db["users"]
    #Returns the total no.of users who has started the bot.
    return len(list(my_col.find({})))


def updateUser(user_id: int, first_name: str, last_name: str, user_name: str) -> None:
    """
    Update a User in the collection (Table).
    """
    my_col = my_db["users"]
    to_update = {
        "user_name": user_name,
        "first_name": first_name,
        "last_name": last_name,
    }
    my_col.update_one({"user_id": user_id}, {"$set":to_update})


def getUser(user_id: int) -> Any or None:
    """
    Returns the user document (Record)
    """
    my_col = my_db["users"]
    return my_col.find_one({"user_id": user_id})


def getLanguage(user_id: int) -> str:
    """
    Gets(Returns) the Language Code of the user. (str)
    """
    my_col = my_db["users"]
    return my_col.find_one({"user_id": user_id})["aki_lang"]


def getChildMode(user_id: int) -> int:
    """
    Get(Returns) the Child mode status of the user. (str)
    """
    my_col = my_db["users"]
    return my_col.find_one({"user_id": user_id})["child_mode"]


def getTotalGuess(user_id: int) -> int:
    """
    
    """
    return my_db["users"].find_one({"user_id": user_id})["total_guess"]


def getCorrectGuess(user_id: int) -> int:
    """
    
    """
    return my_db["users"].find_one({"user_id": user_id})["correct_guess"]



def getWrongGuess(user_id: int) -> int:
    """
    
    """
    return my_db["users"].find_one({"user_id": user_id})["wrong_guess"]


def getUnfinishedGuess(user_id: int) -> int:
    """
    
    """
    crct_wrong_guess = getCorrectGuess(user_id)+getWrongGuess(user_id)
    unfinished_guess = getTotalGuess(user_id)-crct_wrong_guess
    my_db["users"].update_one({"user_id": user_id}, {"$set": {"unfinished_guess": unfinished_guess}})
    return my_db["users"].find_one({"user_id": user_id})["unfinished_guess"]



def getTotalQuestions(user_id: int) -> int:
    """
    
    """
    return my_db["users"].find_one({"user_id": user_id})["total_questions"]



def updateLanguage(user_id: int, lang_code: str) -> None:
    """
    Update Akinator Language for the User.
    """
    my_col = my_db["users"]
    my_col.update_one({"user_id": user_id}, {"$set": {"aki_lang": lang_code}})


def updateChildMode(user_id: int, mode: int) -> None:
    """
    Update Child Mode of the User.
    """
    my_db["users"].update_one({"user_id": user_id}, {"$set": {"child_mode": mode}})

def updateTotalGuess(user_id: int, total_guess: int) -> None:
    """
    
    """
    total_guess = getTotalGuess(user_id)+total_guess
    my_db["users"].update_one({"user_id": user_id}, {"$set": {"total_guess": total_guess}})


def updateCorrectGuess(user_id: int, correct_guess: int) -> None:
    """
    
    """
    correct_guess = getCorrectGuess(user_id)+correct_guess
    my_db["users"].update_one({"user_id": user_id}, {"$set": {"correct_guess": correct_guess}})


def updateWrongGuess(user_id: int, wrong_guess: int) -> None:
    """
    
    """
    wrong_guess = getWrongGuess(user_id)+wrong_guess
    my_db["users"].update_one({"user_id": user_id}, {"$set": {"wrong_guess": wrong_guess}})
    

def updateTotalQuestions(user_id: int, total_questions: int) -> None:
    """
    
    """
    total_questions = total_questions+ getTotalQuestions(user_id)
    my_db["users"].update_one({"user_id": user_id}, {"$set": {"total_questions": total_questions}})


################# LEADERBOARD FUNCTIONS ####################

def getLead(what:str) -> list:
    lead_dict = {}
    for user in my_db['users'].find({}):
        lead_dict.update({user['first_name']: user[what]})
    lead_dict = sorted(lead_dict.items(), key=lambda x: x[1], reverse=True)
    return lead_dict[:10]
