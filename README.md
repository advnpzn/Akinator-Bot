# Akinator-Bot
A Telegram bot where you can play the Akinator Guessing game
check out [Akinator](https://t.me/aki_akinator_bot) on Telegram.

# Deployments
[![Deploy](https://www.herokucdn.com/deploy/button.svg)](https://dashboard.heroku.com/new?button-url=https%3A%2F%2Fgithub.com%2Fadenosinetp10%2FAkinator-bot&template=https%3A%2F%2Fgithub.com%2Fadenosinetp10%2FAkinator-bot
)

[![Deploy on Railway](https://railway.app/button.svg)](https://railway.app/new/template?template=https%3A%2F%2Fgithub.com%2Fadenosinetp10%2FAkinator-Bot&envs=aki_mongo_host%2Cbot_token&aki_mongo_hostDesc=mongoDB+URI+for+accessing+database.&bot_tokenDesc=Telegram+Bot+token+obtained+from+BotFather&referralCode=9C9po6)

## Setting up the database

Akinator uses **MongoDB** by default to store the user stats such as number of games won, abandoned, played and their telegram provided info and also to facilitate for the leaderboard function. MongoDB is easy to set up and work with, noSQL is easy compared to SQL. MongoDB even offers free cloud database for small use. You can create a local mongoDB cluster or use the online mongoDB Atlas to start.. Here, the scope of the following steps is to follow on the footpath of the online setup using mongoDB Atlas.

### steps

1) Go to [mongoDB official site](https://www.mongodb.com/) and login/register.

2) On the Atlas tab, click `create` to create a new cluster.

3) Now configure the cluster as you want such as the cloud service provider, region, cluster tier etc..

4) Now click on the cluster name which will take you to the Overview page.

5) Click `Collections` and create a database called `aki-db`. Inside `aki-db` create a collection called `users`

6) Now on the left side, under the `Security` click the `Database Access` and add a user. Don't forget to note down the username and password!

7) Now go to `Network Access` right under `Database Access` and check whether `0.0.0.0/0` is in the **IP Access List**. If not, then click `Add IP Address` and add `0.0.0.0/0`.

8) Now everything is set up! But there's still one step left, i.e to copy the mongoDB address to your database to be accessed by Akinator.

9) Now under the `Deployment` tab, click `Databases` and you should see the cluster you created. Now click the button named `Connect`. Choose `Connect your application`. Select `python` as Driver and appropriate version.

10) It should now give you a template string and will give you instructions on what need to be changed/replaced with. It usually askes you to replace `<username>`, `<password>` and `myFirstDatabase`.

11) Do you now remember step 6 ? Where you should have noted down the username and password. yeah, now you have to replace the username, password. And for `myFirstDatabase`, replace it with your `cluster` name.

12) Everything's done! Finally just copy the string and paste it in the appropriate environmenal variable.


 
# Commands
`/start` - Start the bot

`/language` - Change language of the questions asked by Akinator ( This doesn't change the language of the bot interface! )

`/childmode` - Enable/Disable NSFW Content

`/play` - Start playing!

`/me` - Shows stats about you.

`/leaderboard` - Check leaderboard. It includes various categories!

## Credits

 1. [NinjaSnail1080's Akinator.py](https://github.com/NinjaSnail1080/akinator.py)
 2. [python-telegram-bot](https://github.com/python-telegram-bot/python-telegram-bot)
 3. [hellboi-atul](https://github.com/hellboi-atul) for heroku deploy button.
