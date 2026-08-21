package com.call4paper.app.ui.calendar

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
import java.time.YearMonth
import javax.inject.Inject

data class CalendarUiState(val month: String, val items: List<ConferenceEntity> = emptyList(), val loading: Boolean = false, val error: String? = null)

@HiltViewModel
class CalendarViewModel @Inject constructor(private val repo: ConferenceRepository) : ViewModel() {
    private val _month = MutableStateFlow(YearMonth.now().toString().substring(0,7)) // YYYY-MM
    private val _state = MutableStateFlow(CalendarUiState(month = _month.value))
    val state: StateFlow<CalendarUiState> = _state.asStateFlow()

    init {
        viewModelScope.launch { _month.collect { m -> refresh(m) } }
        viewModelScope.launch { repo.observeAll().collect { list -> _state.value = _state.value.copy(items = list.filter { it.startDate?.startsWith(_month.value) == true }) } }
    }
    fun setMonth(m: String) { _month.value = m; _state.value = _state.value.copy(month = m) }
    fun refresh(m: String = _month.value) {
        viewModelScope.launch {
            _state.value = _state.value.copy(loading = true, error = null)
            try { repo.refreshCalendar(m); _state.value = _state.value.copy(loading = false) }
            catch (e: Exception) { _state.value = _state.value.copy(loading = false, error = e.message) }
        }
    }
}

@Composable
fun CalendarScreen(onConference: (Int) -> Unit, vm: CalendarViewModel = hiltViewModel()) {
    val s by vm.state.collectAsState()
    Column(Modifier.fillMaxSize().padding(16.dp)) {
        Text("Calendar — ${s.month}", style = MaterialTheme.typography.titleLarge, fontSize = 20.sp)
        if (s.loading) LinearProgressIndicator(Modifier.fillMaxWidth())
        s.error?.let { Text(it, color = MaterialTheme.colorScheme.error, fontSize = 13.sp) }
        LazyColumn(verticalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.fillMaxSize()) {
            items(s.items, key = { it.id }) { c ->
                Card(Modifier.fillMaxWidth().clickable { onConference(c.id) }) {
                    Column(Modifier.padding(12.dp)) { Text(c.title, fontSize = 14.sp); Text("${c.startDate} — ${c.website}", fontSize = 12.sp) }
                }
            }
        }
    }
}
