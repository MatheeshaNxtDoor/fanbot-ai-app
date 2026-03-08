package me.matheesha.fanbotai.ui.analytics

import androidx.lifecycle.LiveData
import androidx.lifecycle.MutableLiveData
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.launch
import me.matheesha.fanbotai.data.local.SettingsRepository
import me.matheesha.fanbotai.data.model.Analytics
import me.matheesha.fanbotai.data.repository.AnalyticsRepository
import me.matheesha.fanbotai.data.repository.Result
import me.matheesha.fanbotai.ui.UiState

class AnalyticsViewModel(settings: SettingsRepository) : ViewModel() {

    private val repo = AnalyticsRepository(settings)

    private val _analytics = MutableLiveData<UiState<Analytics>>(UiState.Idle)
    val analytics: LiveData<UiState<Analytics>> = _analytics

    fun load() {
        _analytics.value = UiState.Loading
        viewModelScope.launch {
            _analytics.value = when (val r = repo.getAnalytics()) {
                is Result.Success -> UiState.Success(r.data)
                is Result.Error   -> UiState.Error(r.message)
            }
        }
    }
}

