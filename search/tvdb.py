# -*- coding: utf-8 -*-

import re, time, urllib, os, tempfile, zipfile
from net import HTTP
from cache import Cache

class TvDb:
    """
    
    API:
        scraper  - скрапер
        search   - поиск сериалов
        movie    - профайл фильма
        
    """
    
    def __init__(self):
        self.api_key = '33DBB309BB2B0ADB'
        
        self.cache = Cache('tvdb.db', 1.0)
        
        self.http = HTTP()
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 6.1; rv:10.0.2) Gecko/20100101 Firefox/10.0.2',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'ru-ru,ru;q=0.8,en-us;q=0.5,en;q=0.3',
            'Cache-Control': 'no-cache',
            'Referer': 'http://www.thetvdb.com/'
        }
        
        
    # API
    
    def scraper(self, search, year=None, season=None):
        try:
            if not isinstance(search, list):
                search = [search]
            tag = 'scraper:' + urllib.quote_plus(":".join(search).encode('utf8'))
        except:
            return None
        else:
            
            if year:
                tag += ':' + str(year)

            
            id = self.cache.get(tag, self._scraper, search, year)
            if not id:
                return None

            if season: return self.get_banners(id)
            
            return self.movie(id)

    def get_banners(self, id):
        import xml.etree.ElementTree as ET
        dirname = tempfile.mkdtemp()
        response = self.http.fetch('http://www.thetvdb.com/api/' + self.api_key + '/series/' + str(id) + '/all/ru.zip', headers=self.headers, download=os.path.join(dirname, 'movie.zip'))
        if response.error:
            self._movie_clear(dirname)
            return False, None

        try:
            filezip = zipfile.ZipFile(os.path.join(dirname, 'movie.zip'), 'r')
            filezip.extractall(dirname)
            filezip.close()
            movie = file(os.path.join(dirname, 'banners.xml'), 'rb').read().decode('utf8')
        except:
            self._movie_clear(dirname)
            return False, None

        self._movie_clear(dirname)

        dom = ET.fromstring(movie)
        if not len(dom):
            return

        def dom2dict(node):
            ret = {}
            for child in node:
                if len(child):
                    ret.setdefault(child.tag.lower(), []).append(dom2dict(child))
                else:
                    ret[child.tag.lower()] = child.text
            return ret

        def update_image_urls(meta):
            if isinstance(meta, dict):
                for k, v in meta.items():
                    if isinstance(v, list):
                        map(update_image_urls, v)
                    elif isinstance(v, dict):
                        update_image_urls(v)
                    elif k in ["banner", "fanart", "poster", "filename", "bannerpath", "vignettepath", "thumbnailpath"] and isinstance(v, basestring):
                        meta[k] = image_url(v)
            return meta

        def image_url(fragment):
            return "%s/banners/%s" % ("http://www.thetvdb.com", fragment)

        return update_image_urls(dom2dict(dom))["banner"]

    def search(self, name):
        return self._search(name)
    
    
    def movie(self, id):
        id = str(id)
        return self.cache.get('movie:' + id, self._movie, id)
    
    
    def _movie(self, id):
        dirname = tempfile.mkdtemp()
        response = self.http.fetch('http://www.thetvdb.com/api/' + self.api_key + '/series/' + id + '/all/ru.zip', headers=self.headers, download=os.path.join(dirname, 'movie.zip'))
        if response.error:
            self._movie_clear(dirname)
            return False, None
        
        try:
            filezip = zipfile.ZipFile(os.path.join(dirname, 'movie.zip'), 'r')
            filezip.extractall(dirname)
            filezip.close()
            movie = file(os.path.join(dirname, 'ru.xml'), 'rb').read().decode('utf8')
        except:
            self._movie_clear(dirname)
            return False, None
        
        self._movie_clear(dirname)
        
        body = re.compile(r'<Series>(.+?)</Series>', re.U|re.S).search(movie)
        if not body:
            return False, None
        
        body = body.group(1)
        
        res = {
            'icon' : None,
            'thumbnail': None,
            'properties': {
                'fanart_image': None,
            },
            'info': {
                'count' : int(id)
            }
        }
        
        # режисеры и сценаристы
        for tag in ('Director', 'Writer'):
            people = {}
            people_list = []
            [people_list.extend(x.split('|')) for x in re.compile(r'<' + tag + r'>([^<]+)</' + tag + r'>', re.U|re.S).findall(movie)]
            [people.update({x: 1}) for x in [x.strip() for x in people_list] if x]
            if people:
                res['info'][tag.lower()] = u', '.join([x for x in people.keys() if x])
        
        for tag, retag, typeof, targettype in (
                    ('plot', 'Overview', None, None),
                    ('mpaa', 'ContentRating', None, None),
                    ('premiered', 'FirstAired', None, None),
                    ('studio', 'Network', None, None),
                    ('title', 'SeriesName', None, None),
                    ('runtime', 'Runtime', None, None),
                    ('votes', 'RatingCount', None, None),
                    ('rating', 'Rating', float, None),
                    ('genre', 'Genre', list, unicode),
                    ('cast', 'Actors', list, None)
                    ):
            r = re.compile(r'<' + retag + r'>([^<]+)</' + retag + r'>', re.U|re.S).search(body)
            if r:
                r = r.group(1).strip()
                if typeof == float:
                    res['info'][tag] = float(r)
                elif typeof == list:
                    if targettype == unicode:
                        res['info'][tag] = u', '.join([x for x in [x.strip() for x in r.split(u'|')] if x])
                    else:
                        res['info'][tag] = [x for x in [x.strip() for x in r.split(u'|')] if x]
                else:
                    res['info'][tag] = r
        
        # год
        if 'premiered' in res['info']:
            res['info']['year'] = int(res['info']['premiered'].split('-')[0])
        
        # постер
        r = re.compile(r'<poster>([^<]+)</poster>', re.U|re.S).search(body)
        if r:
            res['icon'] = 'http://thetvdb.com/banners/' + r.group(1).strip()
            res['thumbnail'] = 'http://thetvdb.com/banners/' + r.group(1).strip()
        
        # фанарт
        r = re.compile(r'<fanart>([^<]+)</fanart>', re.U|re.S).search(body)
        if r:
            res['properties']['fanart_image'] = 'http://thetvdb.com/banners/' + r.group(1).strip()
        
        timeout = True
        # если фильм свежий, то кладем в кэш НЕ на долго (могут быть обновления на сайте)
        if 'year' not in res['info'] or int(res['info']['year']) >= time.gmtime(time.time()).tm_year:
            timeout = 7*24*60*60 #week
        
        return timeout, res
            
    
    def _movie_clear(self, dirname):
        for filename in os.listdir(dirname):
            try:
                os.unlink(os.path.join(dirname, filename))
            except:
                raise
        try:
            os.rmdir(dirname)
        except:
            raise
        
    
    def _search(self, search):
        i=-1
        for name in search:
            i+=1
            response = self.http.fetch('http://www.thetvdb.com/api/GetSeries.php?language=ru&seriesname=' + urllib.quote_plus(name.encode('utf-8','ignore')), headers=self.headers)
            if response.error:
                return None
        
            res = []
            rows = re.compile('<Series>(.+?)</Series>', re.U|re.S).findall(response.body.decode('utf8'))
            if rows:
                recmd = re.compile('<seriesid>([0-9]+)</seriesid>', re.U|re.S)
            
                for row in [x for x in rows if x.find(u'<language>ru</language>') != -1]:
                    r = recmd.search(row)
                    if r:
                        res.append(int(r.group(1)))
                # в некоторых случаях можно найти только по оригинальному названию, 
                # но при этом русское описание есть
                if not res:
                    for row in [x for x in rows if x.find(u'<language>en</language>') != -1]:
                        r = recmd.search(row)
                        if r:
                            res.append(int(r.group(1)))

            if res:
                break
                
        return {'pages': (1, 0, 1, 0), 'data': res}
    
    
    def _scraper(self, name, year):
        timeout = True
        
        # если фильм свежий, то кладем в кэш НЕ на долго (могут быть обновления на сайте)
        if year and year >= time.gmtime(time.time()).tm_year:
            timeout = 7*24*60*60 #week
        
        ids = self._search(name)
        
        if ids is None:
            return False, None
        
        elif not ids['data']:
            # сохраняем пустой результат на 3-е суток
            return 259200, None
        
        else:
            return timeout, ids['data'][0]
    
    
    