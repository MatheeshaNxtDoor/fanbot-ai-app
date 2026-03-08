package me.matheesha.fanbotai.ui.dashboard

import androidx.lifecycle.LiveData
import androidx.lifecycle.MutableLiveData
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.launch
import me.matheesha.fanbotai.data.local.SettingsRepository
import me.matheesha.fanbotai.data.model.BotActionResponse
import me.matheesha.fanbotai.data.model.BotStatus
import me.matheesha.fanbotai.data.repository.BotRepository
import me.matheesha.fanbotai.data.repository.Result
import me.matheesha.fanbotai.ui.UiState

class DashboardViewModel(settings: SettingsRepository) : ViewModel() {

    private val repo = BotRepository(settings)

    private val _status = MutableLiveData<UiState<BotStatus>>(UiState.Idle)
    val status: LiveData<UiState<BotStatus>> = _status

    private val _action = MutableLiveData<UiState<BotActionResponse>>(UiState.Idle)
    val action: LiveData<UiState<BotActionResponse>> = _action

    fun loadStatus() {
        _status.value = UiState.Loading
        viewModelScope.launch {
            _status.value = when (val r = repo.getStatus()) {
                is Result.Success -> UiState.Success(r.data)
                is Result.Error   -> UiState.Error(r.message)
            }
        }
    }

    fun startBot() = doAction { repo.start() }
    fun stopBot()  = doAction { repo.stop() }
    fun restartBot() = doAction { repo.restart() }

    private fun doAction(call: suspend () -> Result<BotActionResponse>) {
        _action.value = UiState.Loading
        viewModelScope.launch {
            _action.value = when (val r = call()) {
                is Result.Success -> UiState.Success(r.data)
                is Result.Error   -> UiState.Error(r.message)
            }
        }
    }
}

