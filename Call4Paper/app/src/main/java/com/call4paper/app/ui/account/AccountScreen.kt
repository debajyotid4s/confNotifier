package com.call4paper.app.ui.account

import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
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
    fun load() {
        viewModelScope.launch {
            try { val u = api.getMe(); _user.value = Triple(u.username, u.email, u.created_at) } catch (e: Exception) {}
        }
    }
    fun logout(onDone: () -> Unit) {
        viewModelScope.launch { try { api.logout() } catch (_: Exception) {}; tokens.clear(); onDone() }
    }
    fun deleteAccount(onDone: () -> Unit) {
        viewModelScope.launch { try { api.deleteMe() } catch (_: Exception) {}; tokens.clear(); onDone() }
    }
}

@Composable
fun AccountScreen(onLogout: () -> Unit, onBookmarks: () -> Unit, vm: AccountViewModel = hiltViewModel()) {
    val u by vm.user.collectAsState()
    LaunchedEffect(Unit) { vm.load() }
    Column(Modifier.fillMaxSize().padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        Text("Account", style = MaterialTheme.typography.titleLarge, fontSize = 20.sp)
        Text("Username: ${u.first}", fontSize = 14.sp)
        Text("Email: ${u.second}", fontSize = 14.sp)
        Button(onClick = onBookmarks, modifier = Modifier.fillMaxWidth()) { Text("Bookmarks", fontSize = 14.sp) }
        OutlinedButton(onClick = { vm.logout(onLogout) }, modifier = Modifier.fillMaxWidth()) { Text("Logout", fontSize = 14.sp) }
        Button(onClick = { vm.deleteAccount(onLogout) }, colors = ButtonDefaults.buttonColors(containerColor = MaterialTheme.colorScheme.error), modifier = Modifier.fillMaxWidth()) { Text("Delete Account", fontSize = 14.sp) }
    }
}
