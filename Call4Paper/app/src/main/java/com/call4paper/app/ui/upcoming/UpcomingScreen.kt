package com.call4paper.app.ui.upcoming

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.call4paper.app.data.local.ConferenceEntity
import com.call4paper.app.data.repository.ConferenceRepository
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.*
import kotlinx.coroutines.launch
import javax.inject.Inject

@HiltViewModel
class UpcomingViewModel @Inject constructor(private val repo: ConferenceRepository) : ViewModel() {
    private val _state = MutableStateFlow<List<ConferenceEntity>>(emptyList())
    val state: StateFlow<List<ConferenceEntity>> = _state.asStateFlow()
    private val _error = MutableStateFlow<String?>(null)
    val error: StateFlow<String?> = _error.asStateFlow()
    init { refresh() }
    fun refresh() {
        viewModelScope.launch {
            try { repo.refreshUpcoming(30); repo.observeAll().first().let { _state.value = it } }
            catch (e: Exception) { _error.value = e.message }
        }
    }
}

@Composable
fun UpcomingScreen(onConference: (Int) -> Unit, vm: UpcomingViewModel = hiltViewModel()) {
    val items by vm.state.collectAsState()
    val err by vm.error.collectAsState()
    Column(Modifier.fillMaxSize().padding(16.dp)) {
        Text("Upcoming — soonest first", style = MaterialTheme.typography.titleLarge, fontSize = 20.sp)
        err?.let { Text(it, color = MaterialTheme.colorScheme.error) }
        LazyColumn(verticalArrangement = Arrangement.spacedBy(8.dp)) {
            items(items, key = { it.id }) { c ->
                Card(Modifier.fillMaxWidth().clickable { onConference(c.id) }) {
                    Column(Modifier.padding(12.dp)) { Text(c.title, fontSize = 14.sp); Text(c.startDate ?: "", fontSize = 12.sp) }
                }
            }
        }
    }
}
