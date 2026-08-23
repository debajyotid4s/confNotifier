package com.call4paper.app.ui.account

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.call4paper.app.data.local.TokenManager
import com.call4paper.app.data.remote.ApiService
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.launch
import javax.inject.Inject

@HiltViewModel
class AccountViewModel @Inject constructor(private val api: ApiService, private val tokens: TokenManager) : ViewModel() {
    private val _user = MutableStateFlow<Triple<String,String,String?>>(Triple("","",""))
    val user: StateFlow<Triple<String,String,String?>> = _user
    private val _isRefreshing = MutableStateFlow(false)
    val isRefreshing: StateFlow<Boolean> = _isRefreshing
    fun load() {
        viewModelScope.launch {
            _isRefreshing.value = true
            try { val u = api.getMe(); _user.value = Triple(u.username, u.email, u.created_at) } catch (e: Exception) {}
            _isRefreshing.value = false
        }
    }
    fun refresh() { load() }
    private val _error = MutableStateFlow<String?>(null)
    val error: StateFlow<String?> = _error

    fun logout(onDone: () -> Unit) {
        viewModelScope.launch {
            try {
                api.logout()
                tokens.clear()
                _error.value = null
                onDone()
            } catch (e: Exception) {
                _error.value = "Logout failed — check your connection and try again"
            }
        }
    }
    fun deleteAccount(onDone: () -> Unit) {
        viewModelScope.launch {
            try {
                api.deleteMe()
                tokens.clear()
                _error.value = null
                onDone()
            } catch (e: Exception) {
                _error.value = "Delete failed — check your connection and try again"
            }
        }
    }
}

@Composable
@OptIn(ExperimentalMaterial3Api::class)
fun AccountScreen(onLogout: () -> Unit, onBookmarks: () -> Unit, vm: AccountViewModel = hiltViewModel()) {
    val u by vm.user.collectAsState()
    val err by vm.error.collectAsState()
    val isRefreshing by vm.isRefreshing.collectAsState()
    LaunchedEffect(Unit) { vm.load() }
    PullToRefreshBox(isRefreshing = isRefreshing, onRefresh = { vm.refresh() }, modifier = Modifier.fillMaxSize()) {
        Column(
            Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(16.dp)
        ) {
        Text("Account", style = MaterialTheme.typography.headlineSmall, fontSize = 24.sp)
        err?.let { Text(it, color = MaterialTheme.colorScheme.error, fontSize = 13.sp) }
        // Profile card
        Card(
            shape = androidx.compose.foundation.shape.RoundedCornerShape(16.dp),
            colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceVariant),
            modifier = Modifier.fillMaxWidth()
        ) {
            Row(Modifier.padding(16.dp), horizontalArrangement = Arrangement.spacedBy(16.dp)) {
                Box(
                    Modifier.size(56.dp).background(MaterialTheme.colorScheme.primary, shape = androidx.compose.foundation.shape.CircleShape),
                    contentAlignment = androidx.compose.ui.Alignment.Center
                ) {
                    Text(u.first.take(1).uppercase().ifEmpty { "U" }, color = MaterialTheme.colorScheme.onPrimary, fontSize = 24.sp)
                }
                Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                    Text(u.first.ifEmpty { "Loading..." }, style = MaterialTheme.typography.titleMedium, fontSize = 16.sp)
                    Text(u.second.ifEmpty { "—" }, style = MaterialTheme.typography.bodySmall, fontSize = 13.sp, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    u.third?.let { Text("Joined ${it.take(10)}", fontSize = 11.sp, color = MaterialTheme.colorScheme.onSurfaceVariant) }
                }
            }
        }
        // My Conferences section
        Text("My Conferences", style = MaterialTheme.typography.titleSmall, fontSize = 14.sp, color = MaterialTheme.colorScheme.primary)
        Card(Modifier.fillMaxWidth(), shape = androidx.compose.foundation.shape.RoundedCornerShape(12.dp)) {
            Column {
                ListItem(headlineContent = { Text("Bookmarks", fontSize = 15.sp) }, supportingContent = { Text("Saved conferences", fontSize = 12.sp) }, modifier = Modifier.clickable { onBookmarks() })
                Divider()
                ListItem(headlineContent = { Text("Submission deadlines", fontSize = 15.sp) }, supportingContent = { Text("Track your followed deadlines", fontSize = 12.sp) })
            }
        }
        // Settings section
        Text("Settings", style = MaterialTheme.typography.titleSmall, fontSize = 14.sp, color = MaterialTheme.colorScheme.primary)
        Card(Modifier.fillMaxWidth(), shape = androidx.compose.foundation.shape.RoundedCornerShape(12.dp)) {
            Column {
                ListItem(headlineContent = { Text("Notifications", fontSize = 15.sp) }, supportingContent = { Text("Manage push preferences", fontSize = 12.sp) }, trailingContent = { Switch(checked = true, onCheckedChange = {}) })
                Divider()
                ListItem(headlineContent = { Text("Logout", fontSize = 15.sp) }, modifier = Modifier.clickable { vm.logout(onLogout) })
            }
        }
        // Danger zone
        Card(
            shape = androidx.compose.foundation.shape.RoundedCornerShape(12.dp),
            colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.errorContainer),
            modifier = Modifier.fillMaxWidth()
        ) {
            ListItem(
                headlineContent = { Text("Delete Account", color = MaterialTheme.colorScheme.error, fontSize = 15.sp) },
                supportingContent = { Text("Permanently delete your data", fontSize = 12.sp, color = MaterialTheme.colorScheme.error) },
                modifier = Modifier.clickable { vm.deleteAccount(onLogout) }
            )
        }
        Spacer(Modifier.height(16.dp))
        }
    }
}
