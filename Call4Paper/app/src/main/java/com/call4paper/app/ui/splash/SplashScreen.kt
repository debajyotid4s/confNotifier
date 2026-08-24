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
import com.call4paper.app.data.remote.ApiService
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.launch
import javax.inject.Inject
import kotlin.coroutines.cancellation.CancellationException
import retrofit2.HttpException

@HiltViewModel
class SplashViewModel @Inject constructor(
    private val tokens: TokenManager,
    private val api: ApiService
) : ViewModel() {
    fun decide(onAuth: () -> Unit, onLogin: () -> Unit) {
        viewModelScope.launch {
            val t = tokens.peek()
            if (t == null) {
                onLogin()
                return@launch
            }
            try {
                api.getMe()
                onAuth()
            } catch (e: Exception) {
                if (e is CancellationException) throw e
                if (e is HttpException && (e.code() == 401 || e.code() == 403)) {
                    tokens.clear()
                    onLogin()
                } else {
                    onAuth()
                }
            }
        }
    }
}

@Composable
fun SplashScreen(onAuth: () -> Unit, onLogin: () -> Unit, vm: SplashViewModel = hiltViewModel()) {
    LaunchedEffect(Unit) { vm.decide(onAuth, onLogin) }
    Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) { CircularProgressIndicator() }
}
