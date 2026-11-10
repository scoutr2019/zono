package be.zono.tv

import android.content.Context
import android.content.res.Configuration
import org.json.JSONObject
import java.util.Locale

/** Where you stopped in a movie or episode, so "Continue watching" can pick it up. */
data class Progress(val item: Item, val position: Long, val duration: Long, val updated: Long) {
    val fraction: Float get() = if (duration > 0) (position.toFloat() / duration).coerceIn(0f, 1f) else 0f
}

/** Settings on this device only (app-private storage). */
object Prefs {
    private fun prefs(context: Context) = context.getSharedPreferences("zono", Context.MODE_PRIVATE)

    fun source(context: Context): Source? {
        val raw = prefs(context).getString("source", null) ?: return null
        return runCatching {
            val o = JSONObject(raw)
            Source(o.getString("type"), o.optString("server"), o.optString("user"), o.optString("password"), o.optString("m3u"))
        }.getOrNull()
    }

    fun setSource(context: Context, source: Source?) {
        val value = source?.let {
            JSONObject().put("type", it.type).put("server", it.server).put("user", it.user)
                .put("password", it.password).put("m3u", it.m3u).toString()
        }
        prefs(context).edit().putString("source", value).apply()
    }

    fun language(context: Context): String = prefs(context).getString("language", "") ?: ""
    fun setLanguage(context: Context, code: String) = prefs(context).edit().putString("language", code).commit()

    fun uhdFirst(context: Context) = prefs(context).getBoolean("uhd_first", true)
    fun setUhdFirst(context: Context, on: Boolean) = prefs(context).edit().putBoolean("uhd_first", on).apply()

    fun lastChannel(context: Context): String = prefs(context).getString("last_channel", "") ?: ""
    fun setLastChannel(context: Context, id: String) = prefs(context).edit().putString("last_channel", id).apply()

    fun favorites(context: Context): Set<String> = prefs(context).getStringSet("favorites", emptySet())?.toSet() ?: emptySet()
    fun toggleFavorite(context: Context, id: String): Set<String> {
        val now = favorites(context).toMutableSet()
        if (!now.remove(id)) now.add(id)
        prefs(context).edit().putStringSet("favorites", now).apply()
        return now
    }

    fun progress(context: Context): List<Progress> {
        val raw = prefs(context).getString("progress", null) ?: return emptyList()
        return runCatching {
            val o = JSONObject(raw)
            o.keys().asSequence().mapNotNull { id ->
                val p = o.getJSONObject(id)
                val item = Item(id = id, kind = p.optString("kind", "movie"), title = p.optString("title"),
                    image = p.optString("image"), url = p.optString("url"), group = p.optString("group"),
                    sid = p.optString("sid"), number = p.optInt("number"))
                Progress(item, p.optLong("pos"), p.optLong("dur"), p.optLong("t"))
            }.sortedByDescending { it.updated }.toList()
        }.getOrDefault(emptyList())
    }

    /** Saves the position; nearly finished (or barely started) titles are taken off the list. */
    fun saveProgress(context: Context, item: Item, position: Long, duration: Long) {
        val all = progress(context).filter { it.item.id != item.id }.toMutableList()
        val done = duration > 0 && position > duration * 0.94
        if (!done && position > 60_000) all.add(0, Progress(item, position, duration, System.currentTimeMillis()))
        val o = JSONObject()
        for (p in all.take(40)) {
            o.put(p.item.id, JSONObject().put("kind", p.item.kind).put("title", p.item.title).put("image", p.item.image)
                .put("url", p.item.url).put("group", p.item.group).put("sid", p.item.sid).put("number", p.item.number)
                .put("pos", p.position).put("dur", p.duration).put("t", p.updated))
        }
        prefs(context).edit().putString("progress", o.toString()).apply()
    }

    fun clearAccount(context: Context) {
        prefs(context).edit().remove("source").remove("progress").remove("favorites").remove("last_channel").apply()
        Library.cacheFile(context).delete()
    }
}

object Lang {
    val choices = listOf("", "nl", "fr", "en", "de")

    /** The app in the language chosen in Settings (or the device language). */
    fun wrap(context: Context): Context {
        val code = Prefs.language(context)
        if (code.isEmpty()) return context
        val locale = Locale(code)
        Locale.setDefault(locale)
        val config = Configuration(context.resources.configuration)
        config.setLocale(locale)
        return context.createConfigurationContext(config)
    }

    fun name(code: String) = when (code) {
        "nl" -> "Nederlands"; "fr" -> "Français"; "en" -> "English"; "de" -> "Deutsch"; else -> ""
    }
}
