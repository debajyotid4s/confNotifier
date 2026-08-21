package com.call4paper.app.ui.calendar

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ChevronLeft
import androidx.compose.material.icons.filled.ChevronRight
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
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
import java.time.DayOfWeek
import java.time.LocalDate
import java.time.YearMonth
import java.time.format.TextStyle
import java.util.Locale
import javax.inject.Inject

private val Red = Color(0xFFE53935)
private val RedGradient = Brush.horizontalGradient(listOf(Color(0xFFFF3B30), Color(0xFFD32F2F)))
private val CardBg = Color(0xFFF2F2F7)
private val SelectedBg = Red

data class CalendarUiState(val month: YearMonth = YearMonth.now(), val selected: LocalDate = LocalDate.now(), val items: List<ConferenceEntity> = emptyList(), val loading: Boolean = false, val error: String? = null)

@HiltViewModel
class CalendarViewModel @Inject constructor(private val repo: ConferenceRepository) : ViewModel() {
    private val _month = MutableStateFlow(YearMonth.now())
    private val _selected = MutableStateFlow(LocalDate.now())
    private val _state = MutableStateFlow(CalendarUiState())
    val state: StateFlow<CalendarUiState> = _state.asStateFlow()

    init {
        viewModelScope.launch {
            combine(_month, _selected, repo.observeAll()) { m, sel, list ->
                val monthStr = String.format("%04d-%02d", m.year, m.monthValue)
                CalendarUiState(month = m, selected = sel, items = list.filter {
                    it.abstractDeadline?.startsWith(monthStr) == true || it.fullPaperDeadline?.startsWith(monthStr) == true
                })
            }.collect { _state.value = it }
        }
        viewModelScope.launch { _month.collect { refresh(it) } }
    }
    fun setMonth(m: YearMonth) { _month.value = m }
    fun select(date: LocalDate) { _selected.value = date }
    fun prev() { _month.value = _month.value.minusMonths(1) }
    fun next() { _month.value = _month.value.plusMonths(1) }
    fun refresh(m: YearMonth = _month.value) {
        viewModelScope.launch {
            _state.value = _state.value.copy(loading = true)
            try { repo.refreshCalendar(String.format("%04d-%02d", m.year, m.monthValue)) } catch (e: Exception) { _state.value = _state.value.copy(error = e.message) }
            _state.value = _state.value.copy(loading = false)
        }
    }
}

@Composable
fun CalendarScreen(onConference: (Int) -> Unit, vm: CalendarViewModel = hiltViewModel()) {
    val s by vm.state.collectAsState()
    val conferenceDates = remember(s.items) {
        s.items.flatMap { listOfNotNull(it.abstractDeadline, it.fullPaperDeadline) }
            .mapNotNull { runCatching { LocalDate.parse(it) }.getOrNull() }.toSet()
    }

    Column(
        Modifier.fillMaxSize().background(Color(0xFFF8F8FF)).padding(horizontal = 16.dp).windowInsetsPadding(WindowInsets.statusBars).windowInsetsPadding(WindowInsets.navigationBars)
    ) {
        // Card — matches image: light gray, rounded 20dp, shadow
        Card(
            shape = RoundedCornerShape(20.dp),
            colors = CardDefaults.cardColors(containerColor = CardBg),
            modifier = Modifier.fillMaxWidth().padding(top = 24.dp).shadow(8.dp, RoundedCornerShape(20.dp))
        ) {
            Column(Modifier.padding(16.dp)) {
                // Header: May 2021 + red < >
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically) {
                    Text(
                        s.month.month.getDisplayName(TextStyle.FULL, Locale.ENGLISH) + " " + s.month.year,
                        fontSize = 22.sp, fontWeight = FontWeight.Bold, color = Color.Black
                    )
                    Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                        Box(
                            Modifier.size(36.dp).clip(RoundedCornerShape(8.dp)).background(RedGradient).clickable { vm.prev() },
                            contentAlignment = Alignment.Center
                        ) { Icon(Icons.Filled.ChevronLeft, null, tint = Color.White, modifier = Modifier.size(20.dp)) }
                        Box(
                            Modifier.size(36.dp).clip(RoundedCornerShape(8.dp)).background(RedGradient).clickable { vm.next() },
                            contentAlignment = Alignment.Center
                        ) { Icon(Icons.Filled.ChevronRight, null, tint = Color.White, modifier = Modifier.size(20.dp)) }
                    }
                }
                Spacer(Modifier.height(12.dp))
                Divider(color = Color(0xFFE0E0E0), thickness = 1.dp)
                Spacer(Modifier.height(12.dp))
                // Weekday header Mo..Su
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                    listOf("Mo","Tu","We","Th","Fr","Sa","Su").forEach {
                        Text(it, fontSize = 16.sp, fontWeight = FontWeight.Bold, color = Color.Black, modifier = Modifier.weight(1f), textAlign = TextAlign.Center)
                    }
                }
                Spacer(Modifier.height(8.dp))
                // Dates grid — 6 rows max
                val firstDay = s.month.atDay(1)
                // Monday=1 .. Sunday=7 -> offset 0..6
                val offset = (firstDay.dayOfWeek.value - DayOfWeek.MONDAY.value + 7) % 7
                val daysInMonth = s.month.lengthOfMonth()
                var day = 1
                for (row in 0..5) {
                    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                        for (col in 0..6) {
                            val isEmpty = row == 0 && col < offset
                            val curDay = day
                            val isInMonth = !isEmpty && curDay <= daysInMonth
                            val date = if (isInMonth) s.month.atDay(curDay) else null
                            val isSelected = date != null && date == s.selected
                            val isToday = date != null && date == LocalDate.now()
                            val hasConf = date != null && conferenceDates.contains(date)
                            Box(
                                Modifier.weight(1f).aspectRatio(1f).padding(2.dp).clip(RoundedCornerShape(8.dp))
                                    .background(if (isSelected) SelectedBg else Color.Transparent)
                                    .clickable(enabled = isInMonth) { date?.let { vm.select(it) } },
                                contentAlignment = Alignment.Center
                            ) {
                                if (isInMonth) {
                                    Column(horizontalAlignment = Alignment.CenterHorizontally) {
                                        Text(
                                            "$curDay",
                                            fontSize = 15.sp,
                                            color = when {
                                                isSelected -> Color.White
                                                hasConf -> Red
                                                else -> Color(0xFF222222)
                                            },
                                            fontWeight = if (isSelected) FontWeight.Bold else FontWeight.Normal,
                                            textAlign = TextAlign.Center
                                        )
                                        if (hasConf && !isSelected) Box(Modifier.size(4.dp).clip(RoundedCornerShape(2.dp)).background(Red))
                                    }
                                }
                            }
                            if (isInMonth) day++
                        }
                    }
                    if (day > daysInMonth) break
                }
            }
        }
        Spacer(Modifier.height(20.dp))
        // Month selector Jan..Dec with dots — matches image bottom
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
            for (m in 1..12) {
                val isSel = m == s.month.monthValue
                Column(horizontalAlignment = Alignment.CenterHorizontally, modifier = Modifier.clickable { vm.setMonth(YearMonth.of(s.month.year, m)) }) {
                    Text(
                        YearMonth.of(2021, m).month.getDisplayName(TextStyle.SHORT, Locale.ENGLISH),
                        fontSize = 12.sp,
                        color = if (isSel) Color.Black else Color(0xFF9E9EB8),
                        fontWeight = if (isSel) FontWeight.Bold else FontWeight.Normal
                    )
                    Spacer(Modifier.height(6.dp))
                    Box(
                        Modifier.size(18.dp).clip(RoundedCornerShape(9.dp))
                            .background(if (isSel) Red else Color.White)
                            .then(if (!isSel) Modifier.shadow(2.dp, RoundedCornerShape(9.dp)) else Modifier)
                    )
                }
            }
        }
        Spacer(Modifier.height(12.dp))
        if (s.loading) LinearProgressIndicator(Modifier.fillMaxWidth())
        s.error?.let { Text(it, color = MaterialTheme.colorScheme.error, fontSize = 13.sp) }
        // Agenda for selected date — show deadlines, not start dates
        val selStr = s.selected.toString()
        val forDay = s.items.filter { it.abstractDeadline == selStr || it.fullPaperDeadline == selStr }
        if (forDay.isNotEmpty()) {
            Spacer(Modifier.height(12.dp))
            Text("Deadlines on ${s.selected} — ${forDay.size} conference(s)", fontSize = 14.sp, fontWeight = FontWeight.Bold)
            LazyColumn(verticalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.fillMaxWidth().weight(1f)) {
                items(forDay, key = { it.id }) { c ->
                    val isAbstract = c.abstractDeadline == selStr
                    val label = if (isAbstract) "Abstract" else "Full Paper"
                    val updated = isAbstract // abstract has no previous in this data; full paper would check previous if available
                    Card(Modifier.fillMaxWidth().clickable { onConference(c.id) }, colors = CardDefaults.cardColors(containerColor = Color.White), elevation = CardDefaults.cardElevation(defaultElevation = 2.dp)) {
                        Column(Modifier.padding(12.dp)) {
                            Text(c.title, fontSize = 14.sp, fontWeight = FontWeight.Medium, maxLines = 2)
                            Spacer(Modifier.height(4.dp))
                            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                                Text("⏰ $label: $selStr", fontSize = 12.sp, color = Red, fontWeight = FontWeight.Bold)
                                if (c.abstractDeadline != null && c.fullPaperDeadline != null && c.abstractDeadline != c.fullPaperDeadline) {
                                    Text("• also ${if (isAbstract) c.fullPaperDeadline else c.abstractDeadline}", fontSize = 11.sp, color = Color.Gray)
                                }
                            }
                            Text(c.website ?: "", fontSize = 11.sp, color = Color.Gray, maxLines = 1)
                        }
                    }
                }
            }
        } else {
            Spacer(Modifier.height(12.dp))
            Text("No submission deadlines on ${s.selected}", fontSize = 13.sp, color = Color.Gray)
        }
    }
}
