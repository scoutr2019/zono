package be.zono.tv

import com.google.gson.JsonArray
import com.google.gson.JsonElement
import com.google.gson.JsonObject
import com.google.gson.JsonParser
import com.google.gson.stream.JsonReader
import com.google.gson.stream.JsonToken
import com.google.gson.stream.JsonWriter
import java.io.IOException
import java.io.InputStream
import java.io.InputStreamReader
import java.io.Reader
import java.io.Writer
import java.net.HttpURLConnection
import java.net.URL
import java.net.URLEncoder

/** One channel, movie, series or episode. `group` is "" for "Other". */
data class Item(
    val id: String,
    val kind: String, // live, movie, series, episode
    val title: String,
    val group: String = "",
    val image: String = "",
    val url: String = "",
    val sid: String = "",
    val rating: Double = 0.0,
    val added: Long = 0,
    val backdrop: String = "",
    val epg: String = "",
    val plot: String = "",
    val number: Int = 0, // episode number (episodes only, not cached)
) {
    val uhd: Boolean get() = isUhd("$title $group")
}

/** The subscription: Xtream Codes (server + login) or an M3U link. */
data class Source(val type: String, val server: String = "", val user: String = "", val password: String = "", val m3u: String = "") {
    val isXtream get() = type == "xtream"
}

class LoginError : IOException("login")

private val UHD = Regex("(?<![A-Z0-9])(4K|8K|16K|UHD|2160P?)(?![A-Z0-9])|ᵁᴴᴰ", RegexOption.IGNORE_CASE)

/** A 4K (or better) channel, from the provider's own name or group: "4K | VRT 1", "NPO 1 UHD", "NPO 2ᵁᴴᴰ". */
fun isUhd(text: String) = UHD.containsMatchIn(text)

/** 4K channels first, otherwise the provider's order (stable). */
fun uhdFirst(items: List<Item>): List<Item> = items.sortedBy { if (it.uhd) 0 else 1 }

/** Groups in the order the provider gives them; with `uhdFirst`, groups that are about 4K come first. */
fun groupsOf(items: List<Item>, uhdFirst: Boolean = false): List<String> {
    val groups = LinkedHashSet<String>()
    items.forEach { groups.add(it.group) }
    val list = groups.toList()
    return if (uhdFirst) list.sortedBy { if (isUhd(it)) 0 else 1 } else list
}

fun words(query: String) = query.lowercase().split(Regex("\\s+")).filter { it.isNotBlank() }

fun matches(item: Item, words: List<String>): Boolean {
    if (words.isEmpty()) return false
    val text = item.title.lowercase()
    return words.all { text.contains(it) }
}

object Xtream {
    const val AGENT = "VLC/3.0 LibVLC/3.0"

    /** "example.com:8080/player_api.php?x=1" -> "http://example.com:8080" */
    fun base(server: String): String {
        var text = server.trim()
        if (!text.startsWith("http://", true) && !text.startsWith("https://", true)) text = "http://$text"
        text = text.substringBefore('?').substringBefore('#')
        text = text.replace(Regex("/(?:player_api|get|panel_api)\\.php/?$", RegexOption.IGNORE_CASE), "")
        return text.trimEnd('/')
    }

    fun quote(value: String): String = URLEncoder.encode(value, "UTF-8").replace("+", "%20")

    fun streamUrl(source: Source, kind: String, id: String, extension: String): String {
        val suffix = if (extension.isNotEmpty()) ".$extension" else ""
        return "${base(source.server)}/$kind/${quote(source.user)}/${quote(source.password)}/${quote(id)}$suffix"
    }

    fun apiUrl(source: Source, action: String? = null, extra: Map<String, String> = emptyMap()): String {
        val query = buildString {
            append("username=").append(quote(source.user)).append("&password=").append(quote(source.password))
            if (action != null) append("&action=").append(action)
            extra.forEach { (k, v) -> append('&').append(k).append('=').append(quote(v)) }
        }
        return "${base(source.server)}/player_api.php?$query"
    }

    fun categories(reader: Reader): Map<String, String> {
        val json = JsonReader(reader).apply { isLenient = true }
        val groups = HashMap<String, String>()
        if (json.peek() != JsonToken.BEGIN_ARRAY) return groups
        json.beginArray()
        while (json.hasNext()) {
            if (json.peek() != JsonToken.BEGIN_OBJECT) { json.skipValue(); continue }
            val row = flatObject(json)
            val id = row["category_id"]
            val name = row["category_name"]
            if (id != null && name != null) groups[id] = name
        }
        json.endArray()
        return groups
    }

    /** kind: live, movie or series. The rows are read one by one, so even huge catalogues fit in memory. */
    fun streams(reader: Reader, kind: String, source: Source, groups: Map<String, String>): List<Item> {
        val json = JsonReader(reader).apply { isLenient = true }
        if (json.peek() != JsonToken.BEGIN_ARRAY) {
            json.skipValue()
            throw IOException("no list")
        }
        val key = if (kind == "series") "series_id" else "stream_id"
        val server = base(source.server)
        val items = ArrayList<Item>()
        json.beginArray()
        while (json.hasNext()) {
            if (json.peek() != JsonToken.BEGIN_OBJECT) { json.skipValue(); continue }
            val row = flatObject(json)
            val sid = row[key] ?: continue
            val url = when (kind) {
                "series" -> ""
                "live" -> streamUrl(source, "live", sid, "m3u8")
                else -> streamUrl(source, "movie", sid, row["container_extension"]?.ifBlank { null } ?: "mp4")
            }
            var rating = 0.0
            if (kind != "live") {
                rating = number(row["rating"]).takeIf { it > 0 } ?: (number(row["rating_5based"]) * 2)
                rating = Math.round(minOf(rating, 10.0) * 10) / 10.0
            }
            items.add(
                Item(
                    id = "$server|$kind|$sid", kind = kind, sid = sid,
                    title = row["name"]?.ifBlank { null } ?: sid,
                    group = groups[row["category_id"]] ?: "",
                    image = row["cover"]?.ifBlank { null } ?: row["stream_icon"] ?: "",
                    url = url, rating = rating,
                    added = number(row["added"] ?: row["last_modified"]).toLong(),
                    backdrop = row["backdrop_path"]?.takeIf { it.startsWith("http") } ?: "",
                    epg = if (kind == "live") row["epg_channel_id"] ?: "" else "",
                    plot = row["plot"] ?: "",
                )
            )
        }
        json.endArray()
        return items
    }

    /** Episodes of a series (get_series_info), sorted by season and episode number. */
    fun episodes(reader: Reader, source: Source): List<Item> {
        val root = JsonParser.parseReader(reader)
        if (!root.isJsonObject) return emptyList()
        val server = base(source.server)
        val seasons = root.asJsonObject.get("episodes") ?: return emptyList()
        val pairs = ArrayList<Pair<Int, JsonElement>>()
        when {
            seasons.isJsonObject -> seasons.asJsonObject.entrySet().forEach { (k, v) -> pairs.add((k.toIntOrNull() ?: 0) to v) }
            seasons.isJsonArray -> seasons.asJsonArray.forEachIndexed { i, v -> pairs.add(i + 1 to v) }
        }
        val rows = ArrayList<Triple<Int, Int, Item>>()
        for ((season, list) in pairs.sortedBy { it.first }) {
            if (!list.isJsonArray) continue
            for (element in list.asJsonArray) {
                if (!element.isJsonObject) continue
                val ep = element.asJsonObject
                val id = text(ep, "id") ?: continue
                val number = number(text(ep, "episode_num")).toInt()
                val info = ep.get("info")?.takeIf { it.isJsonObject }?.asJsonObject
                val ext = text(ep, "container_extension")?.ifBlank { null } ?: "mp4"
                val seasonNumber = text(ep, "season")?.toIntOrNull() ?: season
                rows.add(Triple(seasonNumber, number, Item(
                    id = "$server|episode|$id", kind = "episode", sid = id,
                    title = cleanEpisode(text(ep, "title") ?: ""),
                    group = seasonNumber.toString(),
                    image = info?.let { text(it, "movie_image") } ?: "",
                    url = streamUrl(source, "series", id, ext),
                    plot = info?.let { text(it, "plot") } ?: "",
                    number = number,
                )))
            }
        }
        return rows.sortedWith(compareBy({ it.first }, { it.second })).map { it.third }
    }

    /** "NL - Thuis - S30E12 - De brief" -> "De brief"; titles that are only the code become "". */
    fun cleanEpisode(raw: String): String {
        val text = raw.trim()
        val match = Regex("S\\d{1,2}\\s*[ .x]?\\s*E\\d{1,3}\\s*[-:|]?\\s*(.*)$", RegexOption.IGNORE_CASE).find(text)
        return match?.groupValues?.get(1)?.trim() ?: text
    }

    private fun text(obj: JsonObject, key: String): String? {
        val value = obj.get(key) ?: return null
        return when {
            value.isJsonPrimitive -> value.asString
            value.isJsonArray -> (value as JsonArray).firstOrNull { it.isJsonPrimitive }?.asString
            else -> null
        }
    }

    private fun number(value: String?): Double {
        val n = value?.trim()?.toDoubleOrNull() ?: return 0.0
        return if (n.isNaN() || n <= 0) 0.0 else n
    }

    /** One JSON object as text values; arrays give their first text value; nested objects are skipped. */
    private fun flatObject(json: JsonReader): Map<String, String> {
        val row = HashMap<String, String>()
        json.beginObject()
        while (json.hasNext()) {
            val name = json.nextName()
            when (json.peek()) {
                JsonToken.STRING, JsonToken.NUMBER -> row[name] = json.nextString()
                JsonToken.BOOLEAN -> row[name] = json.nextBoolean().toString()
                JsonToken.NULL -> json.nextNull()
                JsonToken.BEGIN_ARRAY -> {
                    json.beginArray()
                    var first: String? = null
                    while (json.hasNext()) {
                        if (first == null && json.peek() == JsonToken.STRING) first = json.nextString() else json.skipValue()
                    }
                    json.endArray()
                    if (first != null) row[name] = first
                }
                else -> json.skipValue()
            }
        }
        json.endObject()
        return row
    }
}

object M3u {
    private val attribute = Regex("([\\w-]+)=\"([^\"]*)\"")

    fun parse(raw: String): List<Item> {
        val items = ArrayList<Item>()
        var info: Map<String, String>? = null
        var title = ""
        for (rawLine in raw.lineSequence()) {
            val line = rawLine.trim()
            if (line.startsWith("#EXTINF:")) {
                info = attribute.findAll(line).associate { it.groupValues[1] to it.groupValues[2] }
                title = splitTitle(line)
            } else if (info != null && line.isNotEmpty() && !line.startsWith("#")) {
                if (line.startsWith("http://", true) || line.startsWith("https://", true)) {
                    val path = line.substringBefore('?').lowercase()
                    val kind = if ("/movie/" in path || path.endsWith(".mp4") || path.endsWith(".mkv") || path.endsWith(".avi")) "movie" else "live"
                    items.add(Item(id = line, kind = kind, title = title.ifBlank { info["tvg-name"] ?: line },
                        group = info["group-title"] ?: "", image = info["tvg-logo"] ?: "", url = line, epg = info["tvg-id"] ?: ""))
                }
                info = null
            }
        }
        return items
    }

    /** The title after the first comma that is not inside quotes (like the Windows app). */
    private fun splitTitle(line: String): String {
        var quoted = false
        for (i in line.indices) {
            val c = line[i]
            if (c == '"') quoted = !quoted
            if (c == ',' && !quoted) return line.substring(i + 1).trim()
        }
        return ""
    }
}

object Net {
    const val LIMIT = 256L * 1024 * 1024

    /** Opens a link like VLC does; follows redirects, also from http to https. */
    fun open(link: String, timeout: Int = 30_000): InputStream {
        var url = link
        repeat(6) {
            val connection = URL(url).openConnection() as HttpURLConnection
            connection.instanceFollowRedirects = false
            connection.connectTimeout = 15_000
            connection.readTimeout = timeout
            connection.setRequestProperty("User-Agent", Xtream.AGENT)
            connection.setRequestProperty("Accept", "*/*")
            val code = connection.responseCode
            if (code in 300..399) {
                val next = connection.getHeaderField("Location") ?: throw IOException("HTTP $code")
                url = URL(URL(url), next).toString()
                connection.disconnect()
                return@repeat
            }
            if (code == 401 || code == 403) throw LoginError()
            if (code !in 200..299) throw IOException("HTTP $code")
            return connection.inputStream
        }
        throw IOException("too many redirects")
    }

    fun reader(link: String): Reader = InputStreamReader(open(link), Charsets.UTF_8)

    fun text(link: String): String = open(link).use { input ->
        val bytes = input.readNBytesCompat(LIMIT)
        String(bytes, Charsets.UTF_8).removePrefix("﻿")
    }

    private fun InputStream.readNBytesCompat(limit: Long): ByteArray {
        val out = java.io.ByteArrayOutputStream()
        val buffer = ByteArray(64 * 1024)
        var total = 0L
        while (true) {
            val n = read(buffer)
            if (n < 0) break
            total += n
            if (total > limit) throw IOException("too big")
            out.write(buffer, 0, n)
        }
        return out.toByteArray()
    }
}

/** Loading the whole library from the provider. */
object Loader {
    fun load(source: Source, step: (String) -> Unit): List<Item> {
        if (!source.isXtream) {
            step("live")
            val items = M3u.parse(Net.text(source.m3u))
            if (items.isEmpty()) throw IOException("empty")
            return items
        }
        // check the login first: a wrong password gives auth=0
        val account = Net.text(Xtream.apiUrl(source))
        val info = runCatching { JsonParser.parseString(account).asJsonObject.getAsJsonObject("user_info") }.getOrNull()
        if (info == null || info.get("auth")?.asString == "0") throw LoginError()
        val all = ArrayList<Item>()
        for ((kind, action) in listOf("live" to "live", "movie" to "vod", "series" to "series")) {
            step(kind)
            val groups = Net.reader(Xtream.apiUrl(source, "get_${action}_categories")).use { Xtream.categories(it) }
            val list = if (kind == "series") "get_series" else "get_${if (kind == "live") "live" else "vod"}_streams"
            all += Net.reader(Xtream.apiUrl(source, list)).use { Xtream.streams(it, kind, source, groups) }
        }
        if (all.isEmpty()) throw IOException("empty")
        return all
    }

    fun episodes(source: Source, series: Item): List<Item> =
        Net.reader(Xtream.apiUrl(source, "get_series_info", mapOf("series_id" to series.sid))).use { Xtream.episodes(it, source) }
}

/** The library on disk, so Zono starts at once next time (and refreshes in the background). */
object Cache {
    fun write(items: List<Item>, writer: Writer) {
        JsonWriter(writer).use { json ->
            json.beginArray()
            for (it in items) {
                json.beginArray()
                json.value(it.id); json.value(it.kind); json.value(it.title); json.value(it.group); json.value(it.image)
                json.value(it.url); json.value(it.sid); json.value(it.rating); json.value(it.added); json.value(it.backdrop)
                json.value(it.epg); json.value(it.plot)
                json.endArray()
            }
            json.endArray()
        }
    }

    fun read(reader: Reader): List<Item> {
        val json = JsonReader(reader)
        val items = ArrayList<Item>()
        json.beginArray()
        while (json.hasNext()) {
            json.beginArray()
            items.add(Item(id = json.nextString(), kind = json.nextString(), title = json.nextString(), group = json.nextString(),
                image = json.nextString(), url = json.nextString(), sid = json.nextString(), rating = json.nextDouble(),
                added = json.nextLong(), backdrop = json.nextString(), epg = json.nextString(), plot = json.nextString()))
            while (json.hasNext()) json.skipValue()
            json.endArray()
        }
        json.endArray()
        return items
    }
}
