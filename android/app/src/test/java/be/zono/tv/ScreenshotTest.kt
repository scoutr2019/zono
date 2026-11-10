package be.zono.tv

import androidx.activity.ComponentActivity
import androidx.compose.ui.test.junit4.createAndroidComposeRule
import androidx.compose.ui.test.onRoot
import com.github.takahirom.roborazzi.captureRoboImage
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import org.robolectric.annotation.GraphicsMode

/** Draws each screen at TV size (1920×1080) into build/screens, to check the layout without a TV. */
@RunWith(RobolectricTestRunner::class)
@GraphicsMode(GraphicsMode.Mode.NATIVE)
@Config(qualifiers = "w960dp-h540dp-land-television-xhdpi", sdk = [34])
class ScreenshotTest {
    @get:Rule val compose = createAndroidComposeRule<ComponentActivity>()

    private fun library() {
        val groups = listOf("4K | Belgie", "Belgie", "Nederland", "Sport", "Documentaires")
        val live = (1..40).map { Item("l$it", "live", listOf("VRT 1", "VTM", "NPO 1", "Play Sports", "Canvas")[it % 5] + if (it % 7 == 0) " 4K" else " HD", groups[it % 5]) }
        val movies = (1..40).map { Item("m$it", "movie", listOf("De Zaak Alzheimer", "Loft", "Dune Part Two", "Oppenheimer", "Ad Astra")[it % 5] + " $it",
            listOf("Actie", "Drama", "Familie")[it % 3], rating = 5.0 + it % 5, added = it.toLong()) }
        val series = (1..20).map { Item("s$it", "series", listOf("Thuis", "De Mol", "Undercover", "Familie")[it % 4] + " $it", "Vlaams", added = it.toLong(), rating = 8.1) }
        Library.source = Source("xtream", "http://demo.example:8080", "demo", "x")
        Library.shelves = Shelves(live + movies + series, true)
        Library.progress = listOf(Progress(movies[3], 40 * 60_000, 120 * 60_000, 1))
        Library.favorites = setOf("l2")
    }

    private fun shot(name: String, page: @androidx.compose.runtime.Composable () -> Unit) {
        compose.setContent { ZonoTheme { page() } }
        compose.waitForIdle()
        compose.onRoot().captureRoboImage("build/screens/$name.png")
    }

    @Test fun login() { Library.source = null; Library.error = ""; shot("1-login") { App() } }
    @Test fun discover() { library(); shot("2-discover") { App() } }
    @Test fun live() { library(); shot("3-live") { androidx.compose.foundation.layout.Row { Menu(Page.Live) {}; Live() } } }
    @Test fun movies() { library(); shot("4-movies") { androidx.compose.foundation.layout.Row { Menu(Page.Movies) {}; Grid(Library.shelves.movies, Library.shelves.movieGroups) { _, _ -> } } } }
    @Test fun settings() { library(); shot("5-settings") { androidx.compose.foundation.layout.Row { Menu(Page.Settings) {}; Settings() } } }
}
