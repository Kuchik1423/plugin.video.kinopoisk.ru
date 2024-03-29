# -*- coding: utf-8 -*-
""" Handles notifications from XBMC via its own thread and forwards them on to the scrobbler """

import sys, re
import xbmc
import xbmcaddon
import xbmcgui

if sys.version_info < (2, 7):
    import simplejson as json
else:
    import json

import globals
from myshowsapi import myshowsAPI
from utilities import Debug, checkScrobblingExclusion, xbmcJsonRequest
from scrobbler import Scrobbler

class NotificationService:

    _scrobbler = None
    
    def __init__(self):
        self.run()

    def _dispatch(self, data):
        Debug("[Notification] Dispatch: %s" % data)
        
        # check if scrobbler thread is still alive
        if not self._scrobbler.isAlive():

            if self.Player._playing and not self._scrobbler.pinging:
                # make sure pinging is set
                self._scrobbler.pinging = True

            Debug("[Notification] Scrobler thread died, restarting.")
            self._scrobbler.start()
        
        action = data["action"]
        if action == "started":
            del data["action"]
            p = {"item": data}
            self._scrobbler.playbackStarted(p)
        elif action == "ended" or action == "stopped":
            self._scrobbler.playbackEnded()
        elif action == "paused":
            self._scrobbler.playbackPaused()
        elif action == "resumed":
            self._scrobbler.playbackResumed()
        elif action == "seek" or action == "seekchapter":
            self._scrobbler.playbackSeek()
        elif action == "scanStarted":
            pass
        elif action == "settingsChanged":
            Debug("[Notification] Settings changed, reloading.")
            globals.myshowsapi.updateSettings()
        else:
            Debug("[Notification] '%s' unknown dispatch action!" % action)

    def run(self):
        Debug("[Notification] Starting")
        
        # setup event driven classes
        self.Player = myshowsPlayer(action = self._dispatch)
        self.Monitor = myshowsMonitor(action = self._dispatch)
        
        # init myshowsapi class
        globals.myshowsapi = myshowsAPI()

        # initalize scrobbler class
        self._scrobbler = Scrobbler(globals.myshowsapi)

        # start loop for events
        while (not xbmc.abortRequested):
            xbmc.sleep(500)
            
        # we aborted
        if xbmc.abortRequested:
            Debug("[Notification] abortRequested received, shutting down.")
            
            # delete player/monitor
            del self.Player
            del self.Monitor
            
            # join scrobbler, to wait for termination
            Debug("[Notification] Joining scrobbler thread to wait for exit.")
            self._scrobbler.join()

class myshowsMonitor(xbmc.Monitor):

    def __init__(self, *args, **kwargs):
        xbmc.Monitor.__init__(self)
        self.action = kwargs["action"]
        Debug("[myshowsMonitor] Initalized")

    # called when database gets updated and return video or music to indicate which DB has been changed
    def onDatabaseUpdated(self, database):
        if database == "video":
            Debug("[myshowsMonitor] onDatabaseUpdated(database: %s)" % database)
            data = {"action": "databaseUpdated"}
            self.action(data)

    # called when database update starts and return video or music to indicate which DB is being updated
    def onDatabaseScanStarted(self, database):
        if database == "video":
            Debug("[myshowsMonitor] onDatabaseScanStarted(database: %s)" % database)
            data = {"action": "scanStarted"}
            self.action(data)

    def onSettingsChanged(self):
        data = {"action": "settingsChanged"}
        self.action(data)
        

class myshowsPlayer(xbmc.Player):

    _playing = False

    def __init__(self, *args, **kwargs):
        xbmc.Player.__init__(self)
        self.action = kwargs["action"]
        Debug("[myshowsPlayer] Initalized")

    # called when xbmc starts playing a file
    def onPlayBackStarted(self):
        #xbmc.sleep(2000)
        self.type = None
        self.id = None
        
        # only do anything if we're playing a video
        if self.isPlayingVideo():
            # get item data from json rpc
            result = xbmcJsonRequest({"jsonrpc": "2.0", "method": "Player.GetItem", "params": {"playerid": 1}, "id": 1})
            Debug("[myshowsPlayer] onPlayBackStarted() - %s" % result)
            
            # check for exclusion
            _filename = self.getPlayingFile()
            if checkScrobblingExclusion(_filename):
                Debug("[myshowsPlayer] onPlayBackStarted() - '%s' is in exclusion settings, ignoring." % _filename)
                return

            try:
                if result['item']['label']=='': result['item']['label']=_filename.replace('\\','/').split('/')[-1]
            except: pass

            self.type = result["item"]["type"]

            data = {"action": "started"}
            
            # check type of item
            if self.type == "unknown":
                # do a deeper check to see if we have enough data to perform scrobbles
                Debug("[myshowsPlayer] onPlayBackStarted() - Started playing a non-library file, checking available data.")
                
                season = xbmc.getInfoLabel("VideoPlayer.Season")
                episode = xbmc.getInfoLabel("VideoPlayer.Episode")
                showtitle = xbmc.getInfoLabel("VideoPlayer.TVShowTitle")
                year = xbmc.getInfoLabel("VideoPlayer.Year")
                
                if season and episode and showtitle:
                    # we have season, episode and show title, can scrobble this as an episode
                    self.type = "episode"
                    data["type"] = "episode"
                    data["season"] = int(season)
                    data["episode"] = int(episode)
                    data["showtitle"] = showtitle
                    data["title"] = xbmc.getInfoLabel("VideoPlayer.Title")
                    Debug("[myshowsPlayer] onPlayBackStarted() - Playing a non-library 'episode' - %s - S%02dE%02d - %s." % (data["title"], data["season"], data["episode"]))
                elif year and not season and not showtitle:
                    # we have a year and no season/showtitle info, enough for a movie
                    self.type = "movie"
                    data["type"] = "movie"
                    data["year"] = int(year)
                    data["title"] = xbmc.getInfoLabel("VideoPlayer.Title")
                    data["titleAlt"]= xbmc.getInfoLabel("VideoPlayer.OriginalTitle")
                    Debug("[myshowsPlayer] onPlayBackStarted() - Playing a non-library 'movie' - %s (%d)." % (data["title"], data["year"]))
                else:
                    Debug("[myshowsPlayer] onPlayBackStarted() - Non-library file, not enough data for scrobbling, try use lable.")
                    try:data["label"]=result["item"]["label"]
                    except: return
                    urls=['(.+)s(\d+)e(\d+)','(.+)s(\d+)\.e(\d+)', '(.+) [\[|\(](\d+)[x|-](\d+)[\]|\)]', '(.+) (\d+)[x|-](\d+)',
                          '(.+)(\d{4})\.(\d{2,4})\.(\d{2,4})','(.+)(\d{4}) (\d{2}) (\d{2})']
                    for file in urls:
                        match=re.compile(file, re.I | re.IGNORECASE).findall(data["label"])
                        if match:
                            self.type = "episode"
                            data["type"] = "episode"
                            break
                    if self.type!="episode":
                        file=data["label"]
                        file=file.replace('.',' ').replace('_',' ').replace('[',' ').replace(']',' ').replace('(',' ').replace(')',' ').strip()
                        match=re.compile('(.+) (\d{4})( |$)', re.I | re.IGNORECASE).findall(file)
                        if match:
                            data["title"], data["year"] = match[0][0],match[0][1]
                            self.type = "movie"
                            data["type"] = "movie"
                            data["year"]=int(data["year"])
                            data["title"]=data["title"].strip()

                    if self.type == "unknown":
                        Debug("[myshowsPlayer] onPlayBackStarted() - Non-library unknown file, stopped scrobble.")

            elif self.type == "episode" or self.type == "movie":
                # get library id
                self.id = result["item"]["id"]
                data["id"] = self.id
                data["type"] = self.type

                if self.type == "movie":
                    data["year"] = xbmc.getInfoLabel("VideoPlayer.Year")
                    data["title"] = xbmc.getInfoLabel("VideoPlayer.Title")
                    data["titleAlt"]= xbmc.getInfoLabel("VideoPlayer.OriginalTitle")
                    if len(data["title"])<1:
                        result = xbmcJsonRequest({"jsonrpc": "2.0", "method": "VideoLibrary.GetMovieDetails", "params": {"movieid": self.id, "properties": ["title", "year","originaltitle"]}, "id": 1})
                        if result:
                            Debug("[myshowsPlayer] onPlayBackStarted() TitleLen0 Event - %s" % result)
                            data["title"] = result["moviedetails"]["title"]
                            data["year"] = int(result["moviedetails"]["year"])
                            data["titleAlt"] = result["moviedetails"]["originaltitle"]

                if self.type == "episode":
                    Debug("[myshowsPlayer] onPlayBackStarted() - Doing multi-part episode check.")
                    result = xbmcJsonRequest({"jsonrpc": "2.0", "method": "VideoLibrary.GetEpisodeDetails", "params": {"episodeid": self.id, "properties": ["tvshowid", "season","episode"]}, "id": 1})
                    if result:
                        Debug("[myshowsPlayer] onPlayBackStarted() - %s" % result)
                        tvshowid = int(result["episodedetails"]["tvshowid"])
                        season = int(result["episodedetails"]["season"])
                        episode = int(result["episodedetails"]["episode"])
                        episode_index = episode - 1
                        
                        result = xbmcJsonRequest({"jsonrpc": "2.0", "method": "VideoLibrary.GetEpisodes", "params": {"tvshowid": tvshowid, "season": season, "properties": ["episode", "file"], "sort": {"method": "episode"}}, "id": 1})
                        if result:
                            Debug("[myshowsPlayer] onPlayBackStarted() - %s" % result)
                            # make sure episodes array exists in results
                            if result.has_key("episodes"):
                                multi = []
                                for i in range(episode_index, result["limits"]["total"]):
                                    if result["episodes"][i]["file"] == result["episodes"][episode_index]["file"]:
                                        multi.append(result["episodes"][i]["episodeid"])
                                    else:
                                        break
                                if len(multi) > 1:
                                    data["multi_episode_data"] = multi
                                    data["multi_episode_count"] = len(multi)
                                    Debug("[myshowsPlayer] onPlayBackStarted() - This episode is part of a multi-part episode.")
            else:
                Debug("[myshowsPlayer] onPlayBackStarted() - Video type '%s' unrecognized, skipping." % self.type)
                return

            self._playing = True
            
            # send dispatch
            Debug("[myshowsPlayer] onPlayBackStarted() - Data '%s'." % data)
            self.action(data)

    # called when xbmc stops playing a file
    def onPlayBackEnded(self):
        if self._playing:
            Debug("[myshowsPlayer] onPlayBackEnded() - %s" % self.isPlayingVideo())
            self._playing = False
            data = {"action": "ended"}
            self.action(data)

    # called when user stops xbmc playing a file
    def onPlayBackStopped(self):
        if self._playing:
            Debug("[myshowsPlayer] onPlayBackStopped() - %s" % self.isPlayingVideo())
            self._playing = False
            data = {"action": "stopped"}
            self.action(data)

    # called when user pauses a playing file
    def onPlayBackPaused(self):
        if self._playing:
            Debug("[myshowsPlayer] onPlayBackPaused() - %s" % self.isPlayingVideo())
            data = {"action": "paused"}
            self.action(data)

    # called when user resumes a paused file
    def onPlayBackResumed(self):
        if self._playing:
            Debug("[myshowsPlayer] onPlayBackResumed() - %s" % self.isPlayingVideo())
            data = {"action": "resumed"}
            self.action(data)

    # called when user queues the next item
    def onQueueNextItem(self):
        if self._playing:
            Debug("[myshowsPlayer] onQueueNextItem() - %s" % self.isPlayingVideo())

    # called when players speed changes. (eg. user FF/RW)
    def onPlayBackSpeedChanged(self, speed):
        if self._playing:
            Debug("[myshowsPlayer] onPlayBackSpeedChanged(speed: %s) - %s" % (str(speed), self.isPlayingVideo()))

    # called when user seeks to a time
    def onPlayBackSeek(self, time, offset):
        if self._playing:
            Debug("[myshowsPlayer] onPlayBackSeek(time: %s, offset: %s) - %s" % (str(time), str(offset), self.isPlayingVideo()))
            data = {"action": "seek"}
            self.action(data)

    # called when user performs a chapter seek
    def onPlayBackSeekChapter(self, chapter):
        if self._playing:
            Debug("[myshowsPlayer] onPlayBackSeekChapter(chapter: %s) - %s" % (str(chapter), self.isPlayingVideo()))
            data = {"action": "seekchapter"}
            self.action(data)
