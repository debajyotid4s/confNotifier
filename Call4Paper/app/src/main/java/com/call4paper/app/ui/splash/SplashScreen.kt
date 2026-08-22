package com.call4paper.app.ui.splash

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.call4paper.app.data.local.TokenManager
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.launch
import javax.inject.Inject

@HiltViewModel
class SplashViewModel @Inject constructor(private val tokens: TokenManager) : ViewModel() {
    fun decide(onAuth: () -> Unit, onLogin: () -> Unit) {
        viewModelScope.launch {
            val t = tokens.peek()
            if (t != null && isJwtValid(t)) onAuth() else {
                if (t != null) tokens.clear() // expired/invalid → clear stale token
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
            if (exp == 0L) return true // no exp claim → treat as valid (server should always set it)
            val nowSec = System.currentTimeMillis() / 1000L
            // 60s clock skew leeway
            exp > nowSec + 60
        } catch (_: Exception) { false }
    }
}

@Composable
fun SplashScreen(onAuth: () -> Unit, onLogin: () -> Unit, vm: SplashViewModel = hiltViewModel()) {
    LaunchedEffect(Unit) { vm.decide(onAuth, onLogin) }
    Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) { CircularProgressIndicator() }
}
