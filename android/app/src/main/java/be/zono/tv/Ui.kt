package be.zono.tv

import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.focus.onFocusChanged
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import coil.compose.AsyncImage

// The colours of Zono for Windows
val Bg = Color(0xFF0B0B0F)
val Side = Color(0xFF111116)
val Panel = Color(0xFF18181F)
val Raised = Color(0xFF23232B)
val Line = Color(0xFF2B2B34)
val TextColor = Color(0xFFF5F5F7)
val Soft = Color(0xFFD3D3DB)
val Muted = Color(0xFF9B9BA8)
val Dim = Color(0xFF64646F)
val Accent = Color(0xFF5558F5)
val AccentSoft = Color(0xFF8F91FB)
val LiveRed = Color(0xFFE5243B)
val Gold = Color(0xFFFFCB5C)

private val Pairs = listOf(
    Color(0xFF4C1D95) to Color(0xFFDB2777), Color(0xFF1E3A8A) to Color(0xFF06B6D4), Color(0xFF7C2D12) to Color(0xFFF59E0B),
    Color(0xFF064E3B) to Color(0xFF34D399), Color(0xFF312E81) to Color(0xFFA78BFA), Color(0xFF831843) to Color(0xFFFB7185),
)

@Composable
fun ZonoTheme(content: @Composable () -> Unit) {
    MaterialTheme(
        colorScheme = darkColorScheme(
            primary = Accent, onPrimary = Color.White, background = Bg, onBackground = TextColor,
            surface = Panel, onSurface = TextColor, surfaceVariant = Raised, onSurfaceVariant = Muted, outline = Line,
        ),
        content = content,
    )
}

/** Something you can select with the remote: grows a little and gets a white ring when it has focus. */
@OptIn(ExperimentalFoundationApi::class)
@Composable
fun Focusable(
    modifier: Modifier = Modifier,
    shape: RoundedCornerShape = RoundedCornerShape(10.dp),
    grow: Float = 1.06f,
    onLongClick: (() -> Unit)? = null,
    onClick: () -> Unit,
    content: @Composable (Boolean) -> Unit,
) {
    var focused by remember { mutableStateOf(false) }
    val scale by animateFloatAsState(if (focused) grow else 1f, label = "focus")
    Box(
        modifier
            .graphicsLayer { scaleX = scale; scaleY = scale }
            .clip(shape)
            .border(if (focused) 3.dp else 0.dp, if (focused) Color.White else Color.Transparent, shape)
            .onFocusChanged { focused = it.isFocused || it.hasFocus }
            .combinedClickable(
                interactionSource = remember { MutableInteractionSource() }, indication = null,
                onLongClick = onLongClick, onClick = onClick,
            ),
    ) { content(focused) }
}

/** Coloured box with the first letters, shown until (or instead of) the picture. */
@Composable
fun Placeholder(title: String, modifier: Modifier = Modifier, size: Int = 22) {
    val (a, b) = Pairs[(title.hashCode() and 0x7fffffff) % Pairs.size]
    Box(modifier.background(Brush.linearGradient(listOf(a, b))), contentAlignment = Alignment.Center) {
        Text(initials(title), color = Color.White, fontSize = size.sp, fontWeight = FontWeight.Bold)
    }
}

fun initials(title: String): String {
    val parts = title.replace(Regex("^[A-Z]{2,3}\\s*[-|:]\\s*"), "").split(Regex("[^\\p{L}\\p{N}]+")).filter { it.isNotEmpty() }
    return parts.take(2).joinToString("") { it.take(1).uppercase() }.ifEmpty { "Z" }
}

@Composable
fun Poster(item: Item, width: Dp = 150.dp, progress: Float = 0f, favorite: Boolean = false,
           onLongClick: (() -> Unit)? = null, onClick: () -> Unit) {
    Column(Modifier.width(width)) {
        Focusable(Modifier.fillMaxWidth().aspectRatio(2f / 3f), onLongClick = onLongClick, onClick = onClick) {
            Box(Modifier.fillMaxSize().background(Raised)) {
                Placeholder(item.title, Modifier.fillMaxSize())
                if (item.image.isNotBlank()) {
                    AsyncImage(model = item.image, contentDescription = null, contentScale = ContentScale.Crop, modifier = Modifier.fillMaxSize())
                }
                if (item.rating > 0) Badge(String.format("%.1f", item.rating), Modifier.align(Alignment.TopEnd).padding(6.dp), Color(0xCC000000), Gold)
                if (favorite) Badge("♥", Modifier.align(Alignment.TopStart).padding(6.dp), Color(0xCC000000), Color(0xFFFB7185))
                if (progress > 0f) ProgressBar(progress, Modifier.align(Alignment.BottomCenter).padding(8.dp))
            }
        }
        Spacer(Modifier.height(8.dp))
        Text(item.title, color = Soft, fontSize = 13.sp, maxLines = 1, overflow = TextOverflow.Ellipsis)
    }
}

/** A wide card (16:9) for channels and "Continue watching". */
@Composable
fun WideCard(item: Item, width: Dp = 240.dp, subtitle: String = "", progress: Float = 0f, onClick: () -> Unit) {
    Column(Modifier.width(width)) {
        Focusable(Modifier.fillMaxWidth().aspectRatio(16f / 9f), onClick = onClick) {
            Box(Modifier.fillMaxSize().background(Panel), contentAlignment = Alignment.Center) {
                if (item.image.isNotBlank()) {
                    val logo = item.kind == "live"
                    AsyncImage(model = item.image, contentDescription = null,
                        contentScale = if (logo) ContentScale.Fit else ContentScale.Crop,
                        modifier = if (logo) Modifier.fillMaxSize().padding(22.dp) else Modifier.fillMaxSize())
                } else Placeholder(item.title, Modifier.fillMaxSize())
                if (item.kind == "live" && item.uhd) Badge("4K", Modifier.align(Alignment.TopEnd).padding(8.dp), Accent, Color.White)
                if (progress > 0f) ProgressBar(progress, Modifier.align(Alignment.BottomCenter).padding(8.dp))
            }
        }
        Spacer(Modifier.height(8.dp))
        Text(item.title, color = Soft, fontSize = 13.sp, maxLines = 1, overflow = TextOverflow.Ellipsis)
        if (subtitle.isNotEmpty()) Text(subtitle, color = Dim, fontSize = 12.sp, maxLines = 1)
    }
}

@Composable
fun Badge(text: String, modifier: Modifier = Modifier, background: Color = Accent, color: Color = Color.White) {
    Box(modifier.clip(RoundedCornerShape(6.dp)).background(background).padding(horizontal = 7.dp, vertical = 2.dp)) {
        Text(text, color = color, fontSize = 11.sp, fontWeight = FontWeight.Bold)
    }
}

@Composable
fun ProgressBar(fraction: Float, modifier: Modifier = Modifier) {
    Box(modifier.fillMaxWidth().height(4.dp).clip(RoundedCornerShape(2.dp)).background(Color(0x66FFFFFF))) {
        Box(Modifier.fillMaxHeight().fillMaxWidth(fraction.coerceIn(0.02f, 1f)).background(AccentSoft))
    }
}

/** A pill-shaped button: white when it has focus, filled when `selected`. */
@Composable
fun Pill(text: String, selected: Boolean = false, modifier: Modifier = Modifier, onClick: () -> Unit) {
    Focusable(modifier, shape = RoundedCornerShape(50), grow = 1.04f, onClick = onClick) { focused ->
        val bg = when { focused -> Color.White; selected -> Accent; else -> Raised }
        val fg = if (focused) Bg else TextColor
        Box(Modifier.background(bg).padding(horizontal = 18.dp, vertical = 9.dp)) {
            Text(text, color = fg, fontSize = 14.sp, fontWeight = if (selected) FontWeight.SemiBold else FontWeight.Normal, maxLines = 1)
        }
    }
}

/** A row in a list (groups, channels, settings). */
@Composable
fun ListRow(title: String, modifier: Modifier = Modifier, selected: Boolean = false, image: String? = null,
            badge: String = "", trailing: String = "", onLongClick: (() -> Unit)? = null, onClick: () -> Unit) {
    Focusable(modifier.fillMaxWidth(), shape = RoundedCornerShape(10.dp), grow = 1.02f, onLongClick = onLongClick, onClick = onClick) { focused ->
        val bg = when { focused -> Color.White; selected -> Raised; else -> Color.Transparent }
        val fg = if (focused) Bg else if (selected) TextColor else Soft
        Row(Modifier.background(bg).padding(horizontal = 14.dp, vertical = 10.dp), verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            if (image != null) {
                Box(Modifier.size(width = 64.dp, height = 40.dp).clip(RoundedCornerShape(6.dp)).background(Panel), contentAlignment = Alignment.Center) {
                    if (image.isNotBlank()) AsyncImage(model = image, contentDescription = null, contentScale = ContentScale.Fit, modifier = Modifier.fillMaxSize().padding(4.dp))
                    else Text(initials(title), color = Muted, fontSize = 13.sp, fontWeight = FontWeight.Bold)
                }
            }
            Text(title, color = fg, fontSize = 15.sp, maxLines = 1, overflow = TextOverflow.Ellipsis, modifier = Modifier.weight(1f))
            if (badge.isNotEmpty()) Badge(badge)
            if (trailing.isNotEmpty()) Text(trailing, color = if (focused) Dim else Muted, fontSize = 13.sp)
        }
    }
}

@Composable
fun Heading(text: String, modifier: Modifier = Modifier) {
    Text(text, color = TextColor, fontSize = 20.sp, fontWeight = FontWeight.SemiBold, modifier = modifier)
}

@Composable
fun Logo(modifier: Modifier = Modifier) {
    Image(androidx.compose.ui.res.painterResource(R.drawable.zono_logo), contentDescription = "Zono", modifier = modifier)
}
