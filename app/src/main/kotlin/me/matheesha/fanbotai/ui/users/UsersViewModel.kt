package me.matheesha.fanbotai.ui.users

import androidx.lifecycle.LiveData
import androidx.lifecycle.MutableLiveData
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.launch
import me.matheesha.fanbotai.data.local.SettingsRepository
import me.matheesha.fanbotai.data.model.DashboardUser
import me.matheesha.fanbotai.data.repository.Result
import me.matheesha.fanbotai.data.repository.UsersRepository
import me.matheesha.fanbotai.ui.UiState

class UsersViewModel(settings: SettingsRepository) : ViewModel() {

    private val repo = UsersRepository(settings)

    private val _users = MutableLiveData<UiState<List<DashboardUser>>>(UiState.Idle)
    val users: LiveData<UiState<List<DashboardUser>>> = _users

    fun load() {
        _users.value = UiState.Loading
        viewModelScope.launch {
            _users.value = when (val r = repo.getUsers()) {
                is Result.Success -> UiState.Success(r.data)
                is Result.Error   -> UiState.Error(r.message)
            }
        }
    }

    fun deleteUser(uid: String) {
        viewModelScope.launch {
            repo.deleteUser(uid)
            load()
        }
    }

    fun setPermissions(uid: String, perms: List<String>) {
        viewModelScope.launch {
            repo.setPermissions(uid, perms)
            load()
        }
    }
}

