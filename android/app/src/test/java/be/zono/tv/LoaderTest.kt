package be.zono.tv

import okhttp3.mockwebserver.Dispatcher
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import okhttp3.mockwebserver.RecordedRequest
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

/** Loading a whole library from a small fake Xtream server, like a real provider would answer. */
class LoaderTest {
    private lateinit var server: MockWebServer
    private var agent = ""
    private val base get() = server.url("/").toString().trimEnd('/')

    @Before fun start() {
        server = MockWebServer()
        server.dispatcher = object : Dispatcher() {
            override fun dispatch(request: RecordedRequest): MockResponse {
                agent = request.getHeader("User-Agent") ?: ""
                val url = request.requestUrl!!
                val query = url.encodedQuery ?: ""
                if (url.encodedPath == "/old/player_api.php") return MockResponse().setResponseCode(302).addHeader("Location", "$base/player_api.php?$query")
                if (url.encodedPath == "/list.m3u") return MockResponse().setBody("\uFEFF#EXTM3U\n#EXTINF:-1 group-title=\"BE\",Een\nhttp://x/1.ts\n")
                val good = "username=demo&password=geheim" in query
                val action = url.queryParameter("action")
                return MockResponse().setBody(when {
                    !good -> """{"user_info":{"auth":0}}"""
                    action == null -> """{"user_info":{"auth":1,"status":"Active"},"server_info":{}}"""
                    action.endsWith("_categories") -> """[{"category_id":"1","category_name":"Belgie"}]"""
                    action == "get_live_streams" -> """[{"name":"VRT 1","stream_id":1,"category_id":"1"},{"name":"VRT 1 4K","stream_id":2,"category_id":"1"}]"""
                    action == "get_vod_streams" -> """[{"name":"Film","stream_id":3,"container_extension":"mkv","category_id":"1"}]"""
                    action == "get_series" -> """[{"name":"Thuis","series_id":4,"category_id":"1"}]"""
                    action == "get_series_info" -> """{"episodes":{"1":[{"id":"5","episode_num":1,"title":"Thuis S01E01 - Begin"}]}}"""
                    else -> "[]"
                })
            }
        }
        server.start()
    }

    @After fun stop() = server.shutdown()

    @Test fun loadsEverything() {
        val steps = mutableListOf<String>()
        val source = Source("xtream", base, "demo", "geheim")
        val items = Loader.load(source) { steps.add(it) }
        assertEquals(listOf("live", "movie", "series"), steps)
        assertEquals(listOf("live", "live", "movie", "series"), items.map { it.kind })
        assertEquals("$base/movie/demo/geheim/3.mkv", items[2].url)
        assertEquals(Xtream.AGENT, agent)
        val shelves = Shelves(items, true)
        assertEquals("VRT 1 4K", shelves.live.first().title)
        val episodes = Loader.episodes(source, items[3])
        assertEquals("Begin", episodes.single().title)
    }

    @Test fun followsRedirects() {
        val items = Loader.load(Source("xtream", "$base/old/player_api.php", "demo", "geheim")) {}
        assertTrue(items.isNotEmpty())
    }

    @Test(expected = LoginError::class)
    fun wrongPassword() {
        Loader.load(Source("xtream", base, "demo", "fout")) {}
    }

    @Test fun m3uLink() {
        val items = Loader.load(Source("m3u", m3u = "$base/list.m3u")) {}
        assertEquals("Een", items.single().title)
    }
}
