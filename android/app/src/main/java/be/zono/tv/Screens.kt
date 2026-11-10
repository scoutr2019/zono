package be.zono.tv

import android.app.Activity
import android.content.Context
import android.content.Intent
import android.widget.Toast
import androidx.activity.compose.BackHandler
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.grid.items
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import coil.compose.AsyncImage
import androidx.compose.ui.layout.ContentScale
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.withContext

enum class Page { Discover, Search, Live, Movies, Series, Settings }

/** Opens the player with a list you can zap or skip through. */
fun play(context: Context, queue: List<Item>, index: Int, resume: Boolean = true) {
    if (queue.isEmpty()) return
    Library.queue = queue
    context.startActivity(Intent(context, PlayerActivity::class.java).putExtra("index", index).putExtra("resume", resume))
}

@Composable
fun groupName(group: String) = group.ifBlank { stringResource(R.string.other) }

@Composable
fun App() {
    val source = Library.source
    if (source == null) Login() else Home()
}

// ---------------------------------------------------------------- login

@Composable
fun Login() {
    val context = LocalContext.current
    var xtream by rememberSaveable { mutableStateOf(true) }
    var server by rememberSaveable { mutableStateOf("") }
    var user by rememberSaveable { mutableStateOf("") }
    var password by rememberSaveable { mutableStateOf("") }
    var link by rememberSaveable { mutableStateOf("") }
    var problem by remember { mutableStateOf("") }
    val first = remember { FocusRequester() }
    LaunchedEffect(Unit) { runCatching { first.requestFocus() } }

    fun connect() {
        problem = ""
        val source = if (xtream) Source("xtream", server.trim(), user.trim(), password)
        else Source("m3u", m3u = link.trim())
        val ready = if (xtream) source.server.isNotEmpty() && source.user.isNotEmpty() && source.password.isNotEmpty()
        else source.m3u.startsWith("http")
        if (!ready) { problem = context.getString(R.string.error_fields); return }
        Library.refresh(context, source)
    }

    Row(Modifier.fillMaxSize().background(Bg).padding(56.dp), verticalAlignment = Alignment.CenterVertically) {
        Column(Modifier.weight(1f).padding(end = 48.dp)) {
            Logo(Modifier.width(260.dp))
            Spacer(Modifier.height(32.dp))
            Text(stringResource(R.string.login_title), color = TextColor, fontSize = 30.sp, fontWeight = FontWeight.Bold)
            Spacer(Modifier.height(12.dp))
            Text(stringResource(R.string.login_intro), color = Muted, fontSize = 16.sp)
            Spacer(Modifier.height(24.dp))
            Text(stringResource(R.string.test_build), color = Dim, fontSize = 13.sp)
        }
        Column(Modifier.weight(1f).clip(RoundedCornerShape(18.dp)).background(Panel).padding(28.dp),
            verticalArrangement = Arrangement.spacedBy(14.dp)) {
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                Pill(stringResource(R.string.tab_xtream), selected = xtream, modifier = Modifier.focusRequester(first)) { xtream = true }
                Pill(stringResource(R.string.tab_m3u), selected = !xtream) { xtream = false }
            }
            if (xtream) {
                Field(server, { server = it }, stringResource(R.string.field_server), KeyboardType.Uri)
                Field(user, { user = it }, stringResource(R.string.field_user))
                Field(password, { password = it }, stringResource(R.string.field_password), KeyboardType.Password, secret = true, done = ::connect)
            } else {
                Field(link, { link = it }, stringResource(R.string.field_m3u), KeyboardType.Uri, done = ::connect)
            }
            val message = problem.ifEmpty { Library.error }
            if (message.isNotEmpty()) Text(message, color = Color(0xFFFDA4AF), fontSize = 14.sp)
            if (Library.loading) {
                Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                    CircularProgressIndicator(color = AccentSoft, strokeWidth = 3.dp, modifier = Modifier.width(22.dp).height(22.dp))
                    Text(stepText(Library.step), color = Soft, fontSize = 15.sp)
                }
            } else {
                Pill(stringResource(R.string.connect), selected = true) { connect() }
            }
        }
    }
}

@Composable
fun stepText(step: String) = when (step) {
    "live" -> stringResource(R.string.loading_live)
    "movie" -> stringResource(R.string.loading_movies)
    "series" -> stringResource(R.string.loading_series)
    else -> stringResource(R.string.loading)
}

@Composable
fun Field(value: String, onChange: (String) -> Unit, label: String, type: KeyboardType = KeyboardType.Text,
          secret: Boolean = false, done: (() -> Unit)? = null) {
    OutlinedTextField(
        value = value, onValueChange = onChange, label = { Text(label) }, singleLine = true,
        visualTransformation = if (secret) PasswordVisualTransformation() else androidx.compose.ui.text.input.VisualTransformation.None,
        keyboardOptions = KeyboardOptions(keyboardType = type, imeAction = if (done != null) ImeAction.Done else ImeAction.Next, autoCorrectEnabled = false),
        keyboardActions = KeyboardActions(onDone = { done?.invoke() }),
        colors = OutlinedTextFieldDefaults.colors(
            focusedBorderColor = Color.White, unfocusedBorderColor = Line, focusedLabelColor = Color.White,
            unfocusedLabelColor = Muted, cursorColor = AccentSoft, focusedTextColor = TextColor, unfocusedTextColor = Soft,
        ),
        modifier = Modifier.fillMaxWidth(),
    )
}

// ---------------------------------------------------------------- home

@Composable
fun Home() {
    val context = LocalContext.current
    var page by rememberSaveable { mutableStateOf(Page.Discover) }
    var series by remember { mutableStateOf<Item?>(null) }
    BackHandler(enabled = series != null) { series = null }
    BackHandler(enabled = series == null && page != Page.Discover) { page = Page.Discover }

    Row(Modifier.fillMaxSize().background(Bg)) {
        Menu(page) { page = it; series = null }
        Box(Modifier.weight(1f).fillMaxHeight()) {
            val open = series
            when {
                open != null -> SeriesDetail(open)
                Library.shelves.all.isEmpty() -> Loading()
                page == Page.Discover -> Discover { series = it }
                page == Page.Search -> Search { series = it }
                page == Page.Live -> Live()
                page == Page.Movies -> Grid(Library.shelves.movies, Library.shelves.movieGroups) { list, i -> play(context, list, i) }
                page == Page.Series -> Grid(Library.shelves.series, Library.shelves.seriesGroups) { list, i -> series = list[i] }
                page == Page.Settings -> Settings()
            }
        }
    }
}

@Composable
fun Loading() {
    Column(Modifier.fillMaxSize(), verticalArrangement = Arrangement.Center, horizontalAlignment = Alignment.CenterHorizontally) {
        if (Library.error.isNotEmpty()) {
            val context = LocalContext.current
                    Text(Library.error, color = Soft, fontSize = 16.sp)
            Spacer(Modifier.height(16.dp))
            Pill(stringResource(R.string.retry), selected = true) { Library.source?.let { Library.refresh(context, it) } }
        } else {
            CircularProgressIndicator(color = AccentSoft)
            Spacer(Modifier.height(16.dp))
            Text(stepText(Library.step), color = Muted, fontSize = 15.sp)
        }
    }
}

@Composable
fun Menu(page: Page, onPick: (Page) -> Unit) {
    val entries = listOf(
        Page.Discover to R.string.nav_discover, Page.Search to R.string.nav_search, Page.Live to R.string.nav_live,
        Page.Movies to R.string.nav_movies, Page.Series to R.string.nav_series, Page.Settings to R.string.nav_settings,
    )
    val first = remember { FocusRequester() }
    LaunchedEffect(Unit) { runCatching { first.requestFocus() } }
    Column(Modifier.width(220.dp).fillMaxHeight().background(Side).padding(horizontal = 14.dp, vertical = 28.dp),
        verticalArrangement = Arrangement.spacedBy(6.dp)) {
        Logo(Modifier.width(150.dp).padding(start = 8.dp, bottom = 24.dp))
        for ((target, label) in entries) {
            ListRow(stringResource(label), selected = page == target,
                modifier = if (target == Page.Discover) Modifier.focusRequester(first) else Modifier) { onPick(target) }
        }
    }
}

// ---------------------------------------------------------------- discover

@Composable
fun Discover(openSeries: (Item) -> Unit) {
    val context = LocalContext.current
    val shelves = Library.shelves
    val progress = Library.progress
    val favorites = Library.favorites
    val favoriteChannels = remember(shelves, favorites) { shelves.live.filter { it.id in favorites } }
    LazyColumn(contentPadding = PaddingValues(start = 40.dp, end = 40.dp, top = 32.dp, bottom = 48.dp),
        verticalArrangement = Arrangement.spacedBy(30.dp)) {
        if (progress.isNotEmpty()) item {
            Shelf(stringResource(R.string.continue_watching)) {
                items(progress, key = { it.item.id }) { p ->
                    val sub = if (p.item.kind == "episode") stringResource(R.string.season, p.item.group.toIntOrNull() ?: 0) else ""
                    WideCard(p.item, subtitle = sub, progress = p.fraction) {
                        play(context, progress.map { it.item }, progress.indexOf(p))
                    }
                }
            }
        }
        if (favoriteChannels.isNotEmpty()) item {
            Shelf(stringResource(R.string.favorites)) {
                itemsIndexed(favoriteChannels, key = { _, it -> it.id }) { i, item -> WideCard(item, width = 200.dp) { play(context, favoriteChannels, i) } }
            }
        }
        if (shelves.uhdChannels.isNotEmpty()) item {
            Shelf(stringResource(R.string.uhd_channels)) {
                itemsIndexed(shelves.uhdChannels, key = { _, it -> it.id }) { i, item -> WideCard(item, width = 200.dp) { play(context, shelves.uhdChannels, i) } }
            }
        }
        for ((title, list) in listOf(R.string.new_movies to shelves.newMovies, R.string.top_movies to shelves.topMovies)) {
            if (list.isNotEmpty()) item {
                Shelf(stringResource(title)) {
                    itemsIndexed(list, key = { _, it -> it.id }) { i, item -> Poster(item) { play(context, list, i) } }
                }
            }
        }
        if (shelves.newSeries.isNotEmpty()) item {
            Shelf(stringResource(R.string.new_series)) {
                items(shelves.newSeries, key = { it.id }) { item -> Poster(item) { openSeries(item) } }
            }
        }
        if (shelves.live.isNotEmpty() && shelves.movies.isEmpty() && shelves.uhdChannels.isEmpty()) item {
            val first = shelves.live.take(30)
            Shelf(stringResource(R.string.nav_live)) {
                itemsIndexed(first, key = { _, it -> it.id }) { i, item -> WideCard(item, width = 200.dp) { play(context, first, i) } }
            }
        }
    }
}

@Composable
fun Shelf(title: String, content: androidx.compose.foundation.lazy.LazyListScope.() -> Unit) {
    Column {
        Heading(title, Modifier.padding(bottom = 14.dp))
        LazyRow(horizontalArrangement = Arrangement.spacedBy(18.dp), contentPadding = PaddingValues(vertical = 8.dp, horizontal = 4.dp), content = content)
    }
}

// ---------------------------------------------------------------- live tv

@Composable
fun Live() {
    val context = LocalContext.current
    val shelves = Library.shelves
    val favorites = Library.favorites
    val favoritesLabel = stringResource(R.string.favorites)
    val groups = remember(shelves, favorites.isEmpty()) { (if (favorites.isNotEmpty()) listOf("\u0000fav") else emptyList()) + shelves.liveGroups }
    val last = remember { Prefs.lastChannel(context) }
    var group by rememberSaveable { mutableStateOf(shelves.live.firstOrNull { it.id == last }?.group ?: groups.firstOrNull { it != "\u0000fav" } ?: "") }
    val channels = remember(shelves, group, favorites) {
        if (group == "\u0000fav") shelves.live.filter { it.id in favorites } else shelves.live.filter { it.group == group }
    }
    Row(Modifier.fillMaxSize().padding(top = 28.dp)) {
        Column(Modifier.width(300.dp).fillMaxHeight().padding(horizontal = 16.dp)) {
            Heading(stringResource(R.string.groups), Modifier.padding(start = 8.dp, bottom = 12.dp))
            LazyColumn(verticalArrangement = Arrangement.spacedBy(2.dp), contentPadding = PaddingValues(bottom = 32.dp)) {
                items(groups, key = { it }) { g ->
                    val name = if (g == "\u0000fav") "♥ $favoritesLabel" else groupName(g)
                    ListRow(name, selected = g == group, badge = if (g != "\u0000fav" && isUhd(g)) "4K" else "") { group = g }
                }
            }
        }
        Column(Modifier.weight(1f).fillMaxHeight().padding(end = 32.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.padding(start = 8.dp, bottom = 12.dp)) {
                Heading(if (group == "\u0000fav") favoritesLabel else groupName(group))
                Spacer(Modifier.width(14.dp))
                Text(stringResource(R.string.hold_ok_favorite), color = Dim, fontSize = 12.sp)
            }
            if (channels.isEmpty()) Text(stringResource(R.string.empty_group), color = Muted, modifier = Modifier.padding(8.dp))
            LazyColumn(verticalArrangement = Arrangement.spacedBy(2.dp), contentPadding = PaddingValues(bottom = 32.dp)) {
                itemsIndexed(channels, key = { _, it -> it.id }) { i, channel ->
                    ListRow(channel.title, image = channel.image, badge = if (channel.uhd) "4K" else "",
                        trailing = if (channel.id in favorites) "♥" else "",
                        onLongClick = { Library.favorites = Prefs.toggleFavorite(context, channel.id) }) {
                        Prefs.setLastChannel(context, channel.id)
                        play(context, channels, i)
                    }
                }
            }
        }
    }
}

// ---------------------------------------------------------------- movies & series

@Composable
fun Grid(items: List<Item>, groups: List<String>, onOpen: (List<Item>, Int) -> Unit) {
    var group by rememberSaveable(items.size) { mutableStateOf("\u0000all") }
    val shown = remember(items, group) {
        if (group == "\u0000all") items.sortedByDescending { it.added } else items.filter { it.group == group }
    }
    Column(Modifier.fillMaxSize().padding(top = 28.dp)) {
        LazyRow(horizontalArrangement = Arrangement.spacedBy(10.dp), contentPadding = PaddingValues(horizontal = 40.dp, vertical = 6.dp)) {
            item { Pill(stringResource(R.string.all), selected = group == "\u0000all") { group = "\u0000all" } }
            items(groups, key = { it }) { g -> Pill(groupName(g), selected = g == group) { group = g } }
        }
        Spacer(Modifier.height(12.dp))
        if (shown.isEmpty()) Text(stringResource(R.string.empty_group), color = Muted, modifier = Modifier.padding(40.dp))
        LazyVerticalGrid(columns = GridCells.Fixed(5), contentPadding = PaddingValues(start = 40.dp, end = 40.dp, top = 10.dp, bottom = 48.dp),
            horizontalArrangement = Arrangement.spacedBy(22.dp), verticalArrangement = Arrangement.spacedBy(24.dp)) {
            items(shown.size, key = { shown[it].id }) { i ->
                Poster(shown[i]) { onOpen(shown, i) }
            }
        }
    }
}

@Composable
fun SeriesDetail(series: Item) {
    val context = LocalContext.current
    var episodes by remember(series.id) { mutableStateOf<List<Item>?>(null) }
    var failed by remember(series.id) { mutableStateOf(false) }
    var season by remember(series.id) { mutableStateOf("") }
    LaunchedEffect(series.id) {
        val source = Library.source ?: return@LaunchedEffect
        val result = withContext(Dispatchers.IO) { runCatching { Loader.episodes(source, series) } }
        episodes = result.getOrNull() ?: emptyList()
        failed = result.isFailure
        season = episodes?.firstOrNull()?.group ?: ""
    }
    val progress = Library.progress.associateBy { it.item.id }
    Row(Modifier.fillMaxSize()) {
        Column(Modifier.width(320.dp).fillMaxHeight().padding(32.dp)) {
            Box(Modifier.fillMaxWidth().height(380.dp).clip(RoundedCornerShape(14.dp))) {
                Placeholder(series.title, Modifier.fillMaxSize())
                if (series.image.isNotBlank()) AsyncImage(series.image, null, contentScale = ContentScale.Crop, modifier = Modifier.fillMaxSize())
            }
            Spacer(Modifier.height(16.dp))
            Text(series.title, color = TextColor, fontSize = 22.sp, fontWeight = FontWeight.Bold, maxLines = 3, overflow = TextOverflow.Ellipsis)
            if (series.rating > 0) Text("★ ${series.rating}", color = Gold, fontSize = 14.sp, modifier = Modifier.padding(top = 6.dp))
            if (series.plot.isNotBlank()) Text(series.plot, color = Muted, fontSize = 13.sp, maxLines = 6, overflow = TextOverflow.Ellipsis, modifier = Modifier.padding(top = 10.dp))
        }
        Column(Modifier.weight(1f).fillMaxHeight().padding(top = 32.dp, end = 32.dp)) {
            val list = episodes
            when {
                list == null -> CircularProgressIndicator(color = AccentSoft)
                list.isEmpty() -> Text(stringResource(if (failed) R.string.playback_error else R.string.no_episodes), color = Muted)
                else -> {
                    val seasons = remember(list) { list.map { it.group }.distinct() }
                    val inSeason = remember(list, season) { list.filter { it.group == season } }
                    LazyRow(horizontalArrangement = Arrangement.spacedBy(10.dp), contentPadding = PaddingValues(vertical = 6.dp, horizontal = 4.dp)) {
                        items(seasons, key = { it }) { s -> Pill(stringResource(R.string.season, s.toIntOrNull() ?: 0), selected = s == season) { season = s } }
                    }
                    Spacer(Modifier.height(14.dp))
                    LazyColumn(verticalArrangement = Arrangement.spacedBy(4.dp), contentPadding = PaddingValues(bottom = 32.dp)) {
                        itemsIndexed(inSeason, key = { _, it -> it.id }) { i, ep ->
                            val label = stringResource(R.string.episode, ep.number)
                            val name = if (ep.title.isBlank()) label else "${ep.number}. ${ep.title}"
                            val seen = progress[ep.id]
                            ListRow(name, trailing = seen?.let { "${(it.fraction * 100).toInt()}%" } ?: "") {
                                play(context, inSeason.map { it.forPlayer(series) }, i)
                            }
                        }
                    }
                }
            }
        }
    }
}

// ---------------------------------------------------------------- search

@Composable
fun Search(openSeries: (Item) -> Unit) {
    val context = LocalContext.current
    var query by rememberSaveable { mutableStateOf("") }
    var found by remember { mutableStateOf<List<Item>>(emptyList()) }
    val all = Library.shelves.all
    LaunchedEffect(query, all) {
        delay(250)
        val w = words(query)
        found = withContext(Dispatchers.Default) { all.asSequence().filter { matches(it, w) }.take(120).toList() }
    }
    val first = remember { FocusRequester() }
    LaunchedEffect(Unit) { runCatching { first.requestFocus() } }
    Column(Modifier.fillMaxSize().padding(start = 40.dp, end = 40.dp, top = 28.dp)) {
        Box(Modifier.fillMaxWidth(0.6f).focusRequester(first)) { Field(query, { query = it }, stringResource(R.string.search_hint)) }
        Spacer(Modifier.height(20.dp))
        if (query.isNotBlank() && found.isEmpty()) Text(stringResource(R.string.no_results), color = Muted)
        LazyVerticalGrid(columns = GridCells.Fixed(5), contentPadding = PaddingValues(top = 10.dp, bottom = 48.dp),
            horizontalArrangement = Arrangement.spacedBy(22.dp), verticalArrangement = Arrangement.spacedBy(24.dp)) {
            items(found, key = { it.id }) { item ->
                Poster(item) {
                    when (item.kind) {
                        "series" -> openSeries(item)
                        "live" -> { val list = found.filter { it.kind == "live" }; play(context, list, list.indexOf(item)) }
                        else -> play(context, listOf(item), 0)
                    }
                }
            }
        }
    }
}

// ---------------------------------------------------------------- settings

@Composable
fun Settings() {
    val context = LocalContext.current
    var uhd by remember { mutableStateOf(Prefs.uhdFirst(context)) }
    val language = Prefs.language(context)
    val source = Library.source
    LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(start = 40.dp, end = 120.dp, top = 40.dp, bottom = 40.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        item { Heading(stringResource(R.string.language), Modifier.padding(bottom = 6.dp)) }
        item {
            LazyRow(horizontalArrangement = Arrangement.spacedBy(10.dp), contentPadding = PaddingValues(vertical = 6.dp, horizontal = 4.dp)) {
                items(Lang.choices) { code ->
                    Pill(if (code.isEmpty()) stringResource(R.string.language_system) else Lang.name(code), selected = code == language) {
                        if (code != language) {
                            Prefs.setLanguage(context, code)
                            (context as? Activity)?.recreate()
                        }
                    }
                }
            }
        }
        item { Spacer(Modifier.height(18.dp)); Heading(stringResource(R.string.nav_live), Modifier.padding(bottom = 6.dp)) }
        item {
            ListRow(stringResource(R.string.uhd_first), trailing = stringResource(if (uhd) R.string.on else R.string.off)) {
                uhd = !uhd
                Prefs.setUhdFirst(context, uhd)
                Library.resort(context)
            }
        }
        item { Spacer(Modifier.height(18.dp)); Heading(stringResource(R.string.account), Modifier.padding(bottom = 6.dp)) }
        item {
            val where = when {
                source == null -> ""
                source.isXtream -> "${source.user} @ ${Xtream.base(source.server).substringAfter("://")}"
                else -> source.m3u.substringAfter("://").substringBefore('/')
            }
            Text(where, color = Muted, fontSize = 14.sp, modifier = Modifier.padding(start = 14.dp, bottom = 6.dp))
        }
        item {
            ListRow(stringResource(R.string.refresh), trailing = if (Library.loading) stringResource(R.string.loading) else "") {
                source?.let { Library.refresh(context, it, quiet = true) { ok ->
                    Toast.makeText(context, if (ok) "✓" else context.getString(R.string.error_connect, ""), Toast.LENGTH_SHORT).show()
                } }
            }
        }
        item { ListRow(stringResource(R.string.logout)) { Library.signOut(context) } }
        item {
            Spacer(Modifier.height(24.dp))
            Text(stringResource(R.string.version, BuildConfig.VERSION_NAME) + " · " + stringResource(R.string.test_build), color = Dim, fontSize = 13.sp,
                modifier = Modifier.padding(start = 14.dp))
        }
    }
}

/** An episode as the player and "Continue watching" show it: "Series · 3. Title", with the series poster as fallback. */
fun Item.forPlayer(series: Item): Item {
    val name = if (title.isBlank()) "E$number" else "$number. $title"
    return copy(title = "${series.title} · $name", image = image.ifBlank { series.image })
}
