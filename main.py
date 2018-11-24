# sglobbylink-discord.py
# by Mr Peck (2018)
# project page: https://github.com/itsmrpeck/sglobbylink-discord.py

# IMPORTANT: You must enter your Discord bot token and Steam API key in settings_sglobbylink.py or the bot won't work!

import discord
import asyncio
import urllib.request
import json
import threading
import time
from enum import Enum
from settings_sglobbylink import *

# Default settings for old versions of settings_sglobbylink:
if not "allowImagePosting" in locals():
    allowImagePosting = True

if not "imagePostingCooldownSeconds" in locals():
    imagePostingCooldownSeconds = 60 * 10


versionNumber = "1.24"

steamProfileUrlIdentifier = "steamcommunity.com/id"
steamProfileUrlIdentifierLen = len(steamProfileUrlIdentifier)

steamProfileUrlLongIdentifier = "steamcommunity.com/profiles"
steamProfileUrlLongIdentifierLen = len(steamProfileUrlLongIdentifier)

steamIdTable = {}

steamIdInstructionsOnlyFullURL = "enter your full Steam profile URL, e.g. `!steamid http://steamcommunity.com/id/robinwalker/`. You can get this URL by opening the main Steam window, hovering over your name (next to Store/Library/Community), clicking Profile, right-clicking the page background and choosing Copy Page URL."
steamIdInstructionsPartialURLAllowed = "enter your full Steam profile URL or just the last part, e.g. `!steamid http://steamcommunity.com/id/robinwalker/` or `!steamid robinwalker`. DON'T just enter your current Steam nickname, e.g. `!steamid Jim`, or it will think you are `http://steamcommunity.com/id/Jim/`"

todaysRequestCounts = {}

todaysTotalRequestCount = 0

requestCountsLock = threading.RLock()

lastImagePostedTimestamp = 0

client = discord.Client()

class RequestLimitResult(Enum):
    LIMIT_NOT_REACHED = 1
    USER_LIMIT_JUST_REACHED = 2
    TOTAL_LIMIT_JUST_REACHED = 3
    ALREADY_OVER_LIMIT = 4

class LobbyBotCommand(Enum):
    NONE = 1
    HELP = 2
    STEAMID = 3
    LOBBY = 4

def get_steam_id_instructions():
    if onlyAllowFullProfileURLs:
        return steamIdInstructionsOnlyFullURL
    else:
        return steamIdInstructionsPartialURLAllowed

def save_steam_ids():
    try:
        with open(steamIdFileName, 'w+') as f:
            for steamId in steamIdTable.keys():
                f.write(steamId + " " + steamIdTable[steamId] + "\n")
    except:
        pass

def load_steam_ids():
    global steamIdFileName
    global steamIdTable

    try:
        with open(steamIdFileName, 'r') as f:
            steamIdTable.clear()
            for line in f:
                line = line.rstrip('\n')
                splitLine = line.split(" ")
                if len(splitLine) >= 2:
                    steamIdTable[splitLine[0]] = splitLine[1]
    except:
        pass

def increment_request_count(userIdStr): # returns whether or not the user has hit their daily request limit
    global todaysRequestCounts
    global todaysTotalRequestCount
    global maxDailyRequestsPerUser
    global maxTotalDailyRequests

    if maxDailyRequestsPerUser <= 0:
        return RequestLimitResult.ALREADY_OVER_LIMIT

    with requestCountsLock:

        if todaysTotalRequestCount > maxTotalDailyRequests:
            return RequestLimitResult.ALREADY_OVER_LIMIT

        if userIdStr not in todaysRequestCounts.keys():
            todaysRequestCounts[userIdStr] = 0

        if todaysRequestCounts[userIdStr] > maxDailyRequestsPerUser:
            return RequestLimitResult.ALREADY_OVER_LIMIT

        todaysRequestCounts[userIdStr] += 1
        todaysTotalRequestCount += 1

        if todaysTotalRequestCount > maxTotalDailyRequests:
            return RequestLimitResult.TOTAL_LIMIT_JUST_REACHED

        elif todaysRequestCounts[userIdStr] > maxDailyRequestsPerUser:
            return RequestLimitResult.USER_LIMIT_JUST_REACHED

        else:
            return RequestLimitResult.LIMIT_NOT_REACHED

    return RequestLimitResult.ALREADY_OVER_LIMIT


async def clear_request_counts_once_per_day():
    global todaysRequestCounts
    global todaysTotalRequestCount

    await client.wait_until_ready()
    while not client.is_closed:
        with requestCountsLock:
            todaysRequestCounts.clear()
            todaysTotalRequestCount = 0
        await asyncio.sleep(60*60*24) # task runs every 24 hours

def check_if_image_can_be_posted_and_update_timestamp_if_true():
    global allowImagePosting
    global imagePostingCooldownSeconds
    global lastImagePostedTimestamp      

    if allowImagePosting:
        currentTime = time.time()
        if (currentTime - lastImagePostedTimestamp) >= imagePostingCooldownSeconds:
            lastImagePostedTimestamp = currentTime
            return True

    return False

@client.event
async def on_ready():
    load_steam_ids()
    client.loop.create_task(clear_request_counts_once_per_day())

@client.event
async def on_message(message):

    # all commands start with '!'
    if not message.content.startswith('!'):
        return

    # filter out DMs
    if not allowDirectMessages and not message.channel:
        return

    # filter out messages not on the whitelisted channels
    if channelWhitelistIDs and message.channel:
        channelFound = False
        for channelID in channelWhitelistIDs:
            if channelID == message.channel.id:
                channelFound = True
                break
        if not channelFound:
            return

    # check which command we wanted (and ignore any message that isn't a command)
    if message.content.startswith('!help'):
        botCmd = LobbyBotCommand.HELP
    elif message.content.startswith('!steamid'):
        botCmd = LobbyBotCommand.STEAMID
    elif message.content.startswith('!lobby'):
        botCmd = LobbyBotCommand.LOBBY
    else:
        return

    # rate limit check
    rateLimitResult = increment_request_count(message.author.id)
    if rateLimitResult == RequestLimitResult.ALREADY_OVER_LIMIT:
        return
    elif rateLimitResult == RequestLimitResult.TOTAL_LIMIT_JUST_REACHED:
        await client.send_message(message.channel, "Error: Total daily bot request limit reached. Try again in 24 hours.")
        return
    elif rateLimitResult == RequestLimitResult.USER_LIMIT_JUST_REACHED:
        await client.send_message(message.channel, "Error: Daily request limit reached for user " + message.author.name + ". Try again in 24 hours.")
        return

    # actually execute the command
    if botCmd == LobbyBotCommand.HELP:
        await client.send_message(message.channel, "Hello, I am sglobbylink-discord.py v" + versionNumber + " by Mr Peck.\n\nCommands:\n- `!lobby`: posts the link to your current Steam lobby.\n- `!steamid`: tells the bot what your Steam profile is. You can " + get_steam_id_instructions())
        return

    elif botCmd == LobbyBotCommand.STEAMID:
        words = message.content.split(" ")
        if len(words) < 2:
            await client.send_message(message.channel, "`!steamid` usage: " + get_steam_id_instructions())
            return
        else:
            idStr = words[1]
            idStr = idStr.rstrip('/')

            profileUrlStart = idStr.find(steamProfileUrlIdentifier)
            if profileUrlStart != -1:
                # It's a steam profile URL. Erase everything after the last slash
                lastSlash = idStr.rfind('/')
                if lastSlash >= (profileUrlStart + steamProfileUrlIdentifierLen):
                    idStr = idStr[lastSlash + 1:]
                else:
                    # This is a malformed profile URL, with no slash after "steamcommunity.com/id"
                    await client.send_message(message.channel, "`!steamid` usage: " + get_steam_id_instructions())
                    return;
            else:
                # Try the other type of steam profile URL. Let's copy and paste.
                profileUrlStart = idStr.find(steamProfileUrlLongIdentifier)
                if profileUrlStart != -1:
                    # It's a steam profile URL. Erase everything after the last slash
                    lastSlash = idStr.rfind('/')
                    if lastSlash >= (profileUrlStart + steamProfileUrlLongIdentifierLen):
                        idStr = idStr[lastSlash + 1:]
                    else:
                        # This is a malformed profile URL, with no slash after "steamcommunity.com/profiles"
                        await client.send_message(message.channel, "`!steamid` usage: " + get_steam_id_instructions())
                        return;
                elif onlyAllowFullProfileURLs:
                    # This isn't either type of full profile URL, and we're only allowing full profile URLs
                    await client.send_message(message.channel, "`!steamid` usage: " + get_steam_id_instructions())
                    return

            if len(idStr) > 200:
                await client.send_message(message.channel, "Error: Steam ID too long.")
                return
            elif idStr.isdigit():
                steamIdTable[message.author.id] = idStr
                save_steam_ids()
                await client.send_message(message.channel, "Saved " + message.author.name + "'s Steam ID.")
                return
            else:
                steamIdUrl = "http://api.steampowered.com/ISteamUser/ResolveVanityURL/v0001/?key=" + steamApiKeyIMPORTANT + "&vanityurl=" + idStr
                contents = urllib.request.urlopen(steamIdUrl).read()
                if contents:
                    data = json.loads(contents)
                    if data["response"] is None:
                        await client.send_message(message.channel, "SteamAPI: ResolveVanityURL() failed for " + message.author.name + ". Is the Steam Web API down?")
                        return
                    else:
                        if "steamid" in data["response"].keys():
                            steamIdTable[message.author.id] = data["response"]["steamid"]
                            save_steam_ids()
                            await client.send_message(message.channel, "Saved " + message.author.name + "'s Steam ID.")
                            return
                        else:
                            await client.send_message(message.channel, "Could not find Steam ID: " + idStr + ". Make sure you " + get_steam_id_instructions())
                            return
                else:
                    await client.send_message(message.channel, "Error: failed to find " + message.author.name + "'s Steam ID.")
                    return

    elif botCmd == LobbyBotCommand.LOBBY:
        if message.author.id in steamIdTable.keys():
            steamId = steamIdTable[message.author.id]
            profileUrl = "http://api.steampowered.com/ISteamUser/GetPlayerSummaries/v0002/?key=" + steamApiKeyIMPORTANT + "&steamids=" + steamId
            contents = urllib.request.urlopen(profileUrl).read()
            if contents:
                data = json.loads(contents)
                if "response" in data.keys():
                    pdata = data["response"]["players"][0]
                    if "lobbysteamid" in pdata.keys():
                        steamLobbyUrl = "steam://joinlobby/" + pdata["gameid"] + "/" + pdata["lobbysteamid"] + "/" + steamId
                        gameName = ""
                        if "gameextrainfo" in pdata.keys():
                            gameName = pdata["gameextrainfo"] + " "
                        await client.send_message(message.channel, message.author.name + "'s " + gameName + "lobby: " + steamLobbyUrl)
                        return
                    else:
                        # Steam didn't give us a lobby ID. But why?
                        # Let's test if their profile's Game Details are public by seeing if Steam will tell us how many games they own.
                        ownedGamesUrl = "http://api.steampowered.com/IPlayerService/GetOwnedGames/v0001/?key=" + steamApiKeyIMPORTANT + "&steamid=" + steamId + "&include_played_free_games=1"
                        ownedGamesContents = urllib.request.urlopen(ownedGamesUrl).read()
                        if ownedGamesContents:
                            ownedGamesData = json.loads(ownedGamesContents)
                            if "response" in ownedGamesData.keys():
                                if "game_count" in ownedGamesData["response"].keys() and ownedGamesData["response"]["game_count"] > 0:
                                    # They have public Game Details. Let's make sure we can see their account, and that they're online
                                    if pdata["communityvisibilitystate"] == 3: # If the bot can view whether or not the player's Steam account is online https://developer.valvesoftware.com/wiki/Steam_Web_API#GetPlayerSummaries_.28v0002.29
                                        if "personastate" in pdata.keys() and pdata["personastate"] > 0:
                                            # They have public Game Details, Steam thinks they're online. Let's see if they're in a game!
                                            if "gameid" in pdata.keys():
                                                gameName = ""
                                                if "gameextrainfo" in pdata.keys():
                                                    gameName = pdata["gameextrainfo"]
                                                else:
                                                    gameName = "a game"
                                                await client.send_message(message.channel, "Lobby not found for " + message.author.name + ": Steam thinks you're playing " + gameName + " but not in a lobby. Make sure you're in a lobby.")
                                                return
                                            else:
                                                await client.send_message(message.channel, "Lobby not found for " + message.author.name + ": Steam thinks you're online but not playing a game. Make sure you're in a Steam game.")
                                                return
                                        else:
                                            await client.send_message(message.channel, "Lobby not found for " + message.author.name + ": Steam thinks you're offline. Make sure you're connected to Steam, and not set to Appear Offline on your friends list.")
                                            return
                                    else:
                                        await client.send_message(message.channel, "Lobby not found for " + message.author.name + ": Your profile is not public.")
                                        if check_if_image_can_be_posted_and_update_timestamp_if_true():
                                            await client.send_file(message.channel, "public_profile_instructions.jpg")
                                        return
                                else:
                                    await client.send_message(message.channel, "Lobby not found for " + message.author.name + ": Your profile's Game Details are not public.")
                                    if check_if_image_can_be_posted_and_update_timestamp_if_true():
                                        await client.send_file(message.channel, "public_profile_instructions.jpg")
                                    return
                            else:
                                await client.send_message(message.channel, "SteamAPI: GetOwnedGames() failed for " + message.author.name + ". Is the Steam Web API down?")
                                return
                        else:
                            await client.send_message(message.channel, "SteamAPI: GetOwnedGames() failed for " + message.author.name + ". Is the Steam Web API down?")
                            return
                else:
                    await client.send_message(message.channel, "SteamAPI: GetPlayerSummaries() failed for " + message.author.name + ". Is the Steam Web API down?")
                    return
                        
            else:
                await client.send_message(message.channel, "SteamAPI: GetPlayerSummaries() failed for " + message.author.name + ". Is the Steam Web API down?")
                return
        else:
            await client.send_message(message.channel, "Steam ID not found for " + message.author.name +  ". Type `!steamid` and " + get_steam_id_instructions())
            return

client.run(discordBotTokenIMPORTANT)
