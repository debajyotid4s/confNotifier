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
            if (t != null) onAuth() else onLogin()
        }
    }
}

@Composable
fun SplashScreen(onAuth: () -> Unit, onLogin: () -> Unit, vm: SplashViewModel = hiltViewModel()) {
    LaunchedEffect(Unit) { vm.decide(onAuth, onLogin) }
    Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) { CircularProgressIndicator() }
}
