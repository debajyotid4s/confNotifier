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
                var isOnline = false
                while (waited < 5000 && !isOnline) {
                    delay(500)
                    waited += 500
                    isOnline = networkMonitor.currentlyOnline()
                }
                if (isOnline) decide(onAuth, onLogin) else onTimeout()
            }
        }
    }

    private fun decide(onAuth: () -> Unit, onLogin: () -> Unit) {
        viewModelScope.launch {
            val t = tokens.peek()
            if (t != null) onAuth() else onLogin()
        }
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
