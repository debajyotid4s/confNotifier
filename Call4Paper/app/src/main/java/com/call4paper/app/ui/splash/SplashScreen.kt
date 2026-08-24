package com.call4paper.app.ui.splash

import android.app.Activity
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.call4paper.app.data.local.TokenManager
import com.call4paper.app.data.network.NetworkMonitor
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch
import javax.inject.Inject

@HiltViewModel
class SplashViewModel @Inject constructor(
    private val tokens: TokenManager,
    private val networkMonitor: NetworkMonitor
) : ViewModel() {

    private var networkChecked = false

    fun checkNetworkAndDecide(onAuth: () -> Unit, onLogin: () -> Unit, onOffline: () -> Unit, onTimeout: () -> Unit) {
        if (networkChecked) return
        networkChecked = true
        viewModelScope.launch {
            val online = networkMonitor.isOnline.first()
            if (online) {
                decide(onAuth, onLogin)
            } else {
                onOffline()
                var waited = 0
                while (waited < 5000) {
                    delay(500)
                    waited += 500
                    if (networkMonitor.isOnline.first()) {
                        decide(onAuth, onLogin)
                        return@launch
                    }
                }
                onTimeout()
            }
        }
    }

    private fun decide(onAuth: () -> Unit, onLogin: () -> Unit) {
        viewModelScope.launch {
            val t = tokens.peek()
            if (t != null && isJwtValid(t)) onAuth() else {
                if (t != null) tokens.clear()
                onLogin()
            }
        }
    }

    private fun isJwtValid(token: String): Boolean {
        return try {
            val parts = token.split(".")
            if (parts.size != 3) return false
            val payloadJson = String(android.util.Base64.decode(parts[1], android.util.Base64.URL_SAFE or android.util.Base64.NO_PADDING or android.util.Base64.NO_WRAP), Charsets.UTF_8)
            val exp = org.json.JSONObject(payloadJson).optLong("exp", 0L)
            if (exp == 0L) true
            else {
                val nowSec = System.currentTimeMillis() / 1000L
                exp > nowSec + 60
            }
        } catch (_: Exception) { false }
    }
}

@Composable
fun SplashScreen(
    onAuth: () -> Unit,
    onLogin: () -> Unit,
    vm: SplashViewModel = hiltViewModel()
) {
    val context = LocalContext.current
    var showOfflineDialog by remember { mutableStateOf(false) }

    LaunchedEffect(Unit) {
        vm.checkNetworkAndDecide(
            onAuth = onAuth,
            onLogin = onLogin,
            onOffline = { showOfflineDialog = true },
            onTimeout = {
                showOfflineDialog = false
                (context as? Activity)?.finish()
            }
        )
    }

    if (showOfflineDialog) {
        AlertDialog(
            onDismissRequest = {},
            title = { Text("No internet connection") },
            text = { Text("Please turn on your internet connection. The app will close automatically in a few seconds.") },
            confirmButton = {
                TextButton(onClick = { (context as? Activity)?.finish() }) {
                    Text("Close")
                }
            }
        )
    }

    Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
        CircularProgressIndicator()
    }
}
