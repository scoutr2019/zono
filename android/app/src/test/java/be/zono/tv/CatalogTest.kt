package be.zono.tv

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.StringReader
import java.io.StringWriter

class CatalogTest {
    private val source = Source("xtream", "example.com:8080/player_api.php", "jan peeters", "p@ss/1")

    @Test fun baseAddsSchemeAndDropsApiPath() {
        assertEquals("http://example.com:8080", Xtream.base("example.com:8080/player_api.php"))
        assertEquals("https://tv.example.com", Xtream.base(" https://tv.example.com/ "))
        assertEquals("http://x.org/sub", Xtream.base("http://x.org/sub/get.php?username=a"))
    }

    @Test fun streamUrlQuotesLogin() {
        assertEquals("http://example.com:8080/live/jan%20peeters/p%40ss%2F1/12.m3u8", Xtream.streamUrl(source, "live", "12", "m3u8"))
    }

    @Test fun apiUrl() {
        assertEquals("http://example.com:8080/player_api.php?username=jan%20peeters&password=p%40ss%2F1&action=get_series_info&series_id=7",
            Xtream.apiUrl(source, "get_series_info", mapOf("series_id" to "7")))
    }

    @Test fun uhdDetection() {
        assertTrue(isUhd("4K | VRT 1"))
        assertTrue(isUhd("NPO 1 UHD"))
        assertTrue(isUhd("NPO 2ᵁᴴᴰ"))
        assertTrue(isUhd("Sky 2160p"))
        assertFalse(isUhd("SKY4KIDS"))
        assertFalse(isUhd("BBC One HD"))
    }

    @Test fun uhdChannelsComeFirstInProviderOrder() {
        val items = listOf("A HD", "B 4K", "C", "D UHD").map { Item(it, "live", it) }
        assertEquals(listOf("B 4K", "D UHD", "A HD", "C"), uhdFirst(items).map { it.title })
        val groups = listOf(Item("1", "live", "x", "NL"), Item("2", "live", "y", "NL 4K"), Item("3", "live", "z", "BE"))
        assertEquals(listOf("NL 4K", "NL", "BE"), groupsOf(groups, uhdFirst = true))
        assertEquals(listOf("NL", "NL 4K", "BE"), groupsOf(groups))
    }

    @Test fun xtreamLiveStreams() {
        val groups = Xtream.categories(StringReader("""[{"category_id":"1","category_name":"Belgie"},{"category_id":2,"category_name":"4K"},"junk"]"""))
        assertEquals(mapOf("1" to "Belgie", "2" to "4K"), groups)
        val json = """[
          {"num":1,"name":"VRT 1 HD","stream_id":101,"stream_icon":"http://logo/vrt1.png","category_id":"1","epg_channel_id":"vrt1.be","tv_archive":1},
          {"num":2,"name":"VTM 4K","stream_id":"102","stream_icon":null,"category_id":"2","extra":{"nested":[1,2]}},
          {"name":"no id"}
        ]"""
        val items = Xtream.streams(StringReader(json), "live", source, groups)
        assertEquals(2, items.size)
        assertEquals("http://example.com:8080|live|101", items[0].id)
        assertEquals("http://example.com:8080/live/jan%20peeters/p%40ss%2F1/101.m3u8", items[0].url)
        assertEquals("Belgie", items[0].group)
        assertEquals("vrt1.be", items[0].epg)
        assertEquals("", items[1].image)
        assertTrue(items[1].uhd)
    }

    @Test fun xtreamMoviesAndSeries() {
        val movies = """[{"name":"Film","stream_id":5,"container_extension":"mkv","rating":"7.84","added":"1700000000","category_id":"9",
                          "backdrop_path":["https://img/back.jpg"]},
                         {"name":"Old","stream_id":6,"rating_5based":4.5,"container_extension":""}]"""
        val m = Xtream.streams(StringReader(movies), "movie", source, mapOf("9" to "Actie"))
        assertEquals("http://example.com:8080/movie/jan%20peeters/p%40ss%2F1/5.mkv", m[0].url)
        assertEquals(7.8, m[0].rating, 0.001)
        assertEquals(1_700_000_000L, m[0].added)
        assertEquals("https://img/back.jpg", m[0].backdrop)
        assertEquals("Actie", m[0].group)
        assertEquals(9.0, m[1].rating, 0.001)
        assertTrue(m[1].url.endsWith("/6.mp4"))
        assertEquals("", m[1].group)

        val series = Xtream.streams(StringReader("""[{"name":"Thuis","series_id":77,"cover":"http://c.jpg","plot":"Soap"}]"""), "series", source, emptyMap())
        assertEquals("77", series[0].sid)
        assertEquals("", series[0].url)
        assertEquals("Soap", series[0].plot)
    }

    @Test(expected = java.io.IOException::class)
    fun xtreamErrorObjectIsAnError() {
        Xtream.streams(StringReader("""{"user_info":{"auth":0}}"""), "live", source, emptyMap())
    }

    @Test fun episodesSortedWithCleanTitles() {
        val json = """{"info":{"name":"Thuis"},"episodes":{
            "2":[{"id":"902","episode_num":1,"title":"NL - Thuis - S02E01 - Terug","container_extension":"mkv","season":2}],
            "1":[{"id":"802","episode_num":2,"title":"Thuis S01E02","info":{"movie_image":"http://e2.jpg","plot":"Twee"}},
                 {"id":"801","episode_num":"1","title":"De start"}]}}"""
        val eps = Xtream.episodes(StringReader(json), source)
        assertEquals(listOf("801", "802", "902"), eps.map { it.sid })
        assertEquals("De start", eps[0].title)
        assertEquals("", eps[1].title)
        assertEquals(2, eps[1].number)
        assertEquals("http://e2.jpg", eps[1].image)
        assertEquals("Terug", eps[2].title)
        assertEquals("2", eps[2].group)
        assertEquals("http://example.com:8080/series/jan%20peeters/p%40ss%2F1/902.mkv", eps[2].url)
    }

    @Test fun episodesAsList() {
        val json = """{"episodes":[[{"id":"1","episode_num":1,"title":"Een"}],[{"id":"2","episode_num":1,"title":"Twee"}]]}"""
        assertEquals(listOf("1", "2"), Xtream.episodes(StringReader(json), source).map { it.group })
    }

    @Test fun m3uPlaylist() {
        val raw = """#EXTM3U url-tvg="http://guide.xml"
#EXTINF:-1 tvg-id="een.be" tvg-name="Een" tvg-logo="http://logo/een.png" group-title="Vlaanderen",Eén HD
http://server/live/u/p/1.ts
#EXTINF:-1 group-title="Films, nieuw",De film, deel 2
http://server/movie/u/p/2.mkv
#EXTINF:-1,Zonder link
#EXTVLCOPT:http-user-agent=x
#EXTINF:-1,Rare link
rtmp://server/x
"""
        val items = M3u.parse(raw)
        assertEquals(2, items.size)
        assertEquals("Eén HD", items[0].title)
        assertEquals("Vlaanderen", items[0].group)
        assertEquals("een.be", items[0].epg)
        assertEquals("live", items[0].kind)
        assertEquals("De film, deel 2", items[1].title)
        assertEquals("Films, nieuw", items[1].group)
        assertEquals("movie", items[1].kind)
    }

    @Test fun cacheRoundTrip() {
        val items = listOf(Item("a", "movie", "Film \"1\"", "G", "i", "u", "5", 7.5, 123, "b", "", "plot\nmore"),
            Item("b", "live", "Zender", url = "http://x"))
        val out = StringWriter()
        Cache.write(items, out)
        assertEquals(items, Cache.read(StringReader(out.toString())))
    }

    @Test fun search() {
        val item = Item("1", "movie", "The Lord of the Rings")
        assertTrue(matches(item, words("lord RINGS")))
        assertFalse(matches(item, words("lord hobbit")))
        assertFalse(matches(item, words("  ")))
    }

    @Test fun initialsForPlaceholders() {
        assertEquals("VE", initials("BE - VRT Een"))
        assertEquals("T", initials("Thuis"))
        assertEquals("Z", initials("!!"))
    }
}
