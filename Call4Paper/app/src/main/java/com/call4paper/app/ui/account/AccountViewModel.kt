package com.call4paper.app.ui.account

import android.content.Context
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.call4paper.app.data.local.TokenManager
import com.call4paper.app.data.remote.ApiService
import dagger.hilt.android.lifecycle.HiltViewModel
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import javax.inject.Inject

data class AccountUiState(
    val username: String = "",
    val email: String = "",
    val createdAt: String? = null,
    val notificationsEnabled: Boolean = true,
    val isRefreshing: Boolean = false,
    val error: String? = null,
    val showDeleteConfirm: Boolean = false,
    val deleteConfirmText: String = ""
)

@HiltViewModel
class AccountViewModel @Inject constructor(
    private val api: ApiService,
    private val tokens: TokenManager,
    @ApplicationContext private val appContext: Context
) : ViewModel() {
    private val prefs by lazy { appContext.getSharedPreferences("settings", Context.MODE_PRIVATE) }
    private val _state = MutableStateFlow(AccountUiState(notificationsEnabled = prefs.getBoolean("notifications_enabled", true)))
    val state: StateFlow<AccountUiState> = _state.asStateFlow()

    fun load() {
        viewModelScope.launch {
            _state.update { it.copy(isRefreshing = true) }
            try {
                val u = api.getMe()
                _state.update { it.copy(username = u.username, email = u.email, createdAt = u.created_at, error = null, isRefreshing = false) }
            } catch (e: Exception) {
                _state.update { it.copy(error = "Failed to load profile — ${e.message?.take(80) ?: "check connection"}", isRefreshing = false) }
            }
        }
    }

    fun refresh() { load() }

    fun toggleNotifications(enabled: Boolean) {
        _state.update { it.copy(notificationsEnabled = enabled) }
        prefs.edit().putBoolean("notifications_enabled", enabled).apply()
        val fcm = com.google.firebase.messaging.FirebaseMessaging.getInstance()
        if (enabled) fcm.subscribeToTopic("all_users") else fcm.unsubscribeFromTopic("all_users")
    }

    fun logout(onDone: () -> Unit) {
        viewModelScope.launch {
            try { api.logout() } catch (_: Exception) {}
            tokens.clear()
            _state.update { it.copy(error = null) }
            onDone()
        }
    }

    fun requestDelete() { _state.update { it.copy(showDeleteConfirm = true, deleteConfirmText = "") } }
    fun cancelDelete() { _state.update { it.copy(showDeleteConfirm = false, deleteConfirmText = "") } }
    fun onConfirmTextChanged(text: String) { _state.update { it.copy(deleteConfirmText = text) } }

    fun confirmDelete(onDone: () -> Unit) {
        viewModelScope.launch {
            try {
                api.deleteMe()
                tokens.clear()
                _state.update { it.copy(showDeleteConfirm = false, error = null) }
                onDone()
            } catch (e: retrofit2.HttpException) {
                val msg = try {
                    val body = e.response()?.errorBody()?.string()
                    org.json.JSONObject(body ?: "{}").optString("detail", "Delete failed")
                } catch (_: Exception) { "Delete failed" }
                _state.update { it.copy(error = msg) }
            } catch (e: Exception) {
                _state.update { it.copy(error = "Delete failed — check your connection and try again") }
            }
        }
    }
}
