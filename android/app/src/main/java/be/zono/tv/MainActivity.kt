package be.zono.tv

import android.content.Context
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent

class MainActivity : ComponentActivity() {
    override fun attachBaseContext(base: Context) = super.attachBaseContext(Lang.wrap(base))

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        Library.start(this)
        setContent { ZonoTheme { App() } }
    }

    override fun onResume() {
        super.onResume()
        // back from the player: show the new positions under "Continue watching"
        Library.progress = Prefs.progress(this)
    }
}
