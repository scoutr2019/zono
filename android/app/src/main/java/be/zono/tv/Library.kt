package be.zono.tv

import android.content.Context
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.MainScope
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.io.File

/** The loaded library, split up the way the screens need it. */
class Shelves(all: List<Item>, uhdFirst: Boolean) {
    val all = all
    val live: List<Item> = all.filter { it.kind == "live" }.let { if (uhdFirst) uhdFirst(it) else it }
    val movies: List<Item> = all.filter { it.kind == "movie" }
    val series: List<Item> = all.filter { it.kind == "series" }
    val liveGroups = groupsOf(all.filter { it.kind == "live" }, uhdFirst) // provider order, 4K groups first
    val movieGroups = groupsOf(movies)
    val seriesGroups = groupsOf(series)
    val newMovies = movies.filter { it.added > 0 }.sortedByDescending { it.added }.take(30)
    val topMovies = movies.filter { it.rating >= 7 }.sortedByDescending { it.rating }.take(30)
    val newSeries = series.filter { it.added > 0 }.sortedByDescending { it.added }.take(30)
    val uhdChannels = live.filter { it.uhd }.take(30)
}

/** App-wide state. The player reads `queue` (the channels or episodes you can zap/skip through). */
object Library {
    var source by mutableStateOf<Source?>(null)
    var shelves by mutableStateOf(Shelves(emptyList(), true))
    var loading by mutableStateOf(false)
    var step by mutableStateOf("")
    var error by mutableStateOf("")
    var progress by mutableStateOf<List<Progress>>(emptyList())
    var favorites by mutableStateOf<Set<String>>(emptySet())

    var queue: List<Item> = emptyList()
    private var job: Job? = null
    /** Loading keeps going when you leave the screen that started it. */
    private val scope: CoroutineScope = MainScope()

    fun cacheFile(context: Context) = File(context.filesDir, "library.json")

    fun start(context: Context) {
        source = Prefs.source(context)
        progress = Prefs.progress(context)
        favorites = Prefs.favorites(context)
        val current = source ?: return
        if (shelves.all.isNotEmpty()) return
        scope.launch {
            val cached = withContext(Dispatchers.IO) {
                runCatching { cacheFile(context).bufferedReader().use { Cache.read(it) } }.getOrNull()
            }
            if (!cached.isNullOrEmpty()) {
                shelves = withContext(Dispatchers.Default) { Shelves(cached, Prefs.uhdFirst(context)) }
            }
            refresh(context, current, quiet = !cached.isNullOrEmpty())
        }
    }

    /** Loads everything from the provider. `quiet`: the cached library stays on screen meanwhile. */
    fun refresh(context: Context, with: Source, quiet: Boolean = false, onDone: (Boolean) -> Unit = {}) {
        job?.cancel()
        error = ""
        loading = !quiet
        job = scope.launch {
            val result = withContext(Dispatchers.IO) {
                runCatching {
                    Loader.load(with) { kind -> step = kind }.also { items ->
                        cacheFile(context).bufferedWriter().use { Cache.write(items, it) }
                    }
                }
            }
            loading = false
            step = ""
            result.onSuccess { items ->
                shelves = withContext(Dispatchers.Default) { Shelves(items, Prefs.uhdFirst(context)) }
                if (source != with) {
                    Prefs.setSource(context, with)
                    source = with
                }
                onDone(true)
            }.onFailure { problem ->
                if (!quiet) {
                    error = when (problem) {
                        is LoginError -> context.getString(R.string.error_login)
                        else -> if (problem.message == "empty") context.getString(R.string.error_empty)
                        else context.getString(R.string.error_connect, problem.message ?: problem.javaClass.simpleName)
                    }
                }
                onDone(false)
            }
        }
    }

    fun resort(context: Context) {
        shelves = Shelves(shelves.all, Prefs.uhdFirst(context))
    }

    fun signOut(context: Context) {
        job?.cancel()
        Prefs.clearAccount(context)
        source = null
        shelves = Shelves(emptyList(), true)
        progress = emptyList()
        favorites = emptySet()
        loading = false
        error = ""
    }
}
