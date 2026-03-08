package me.matheesha.fanbotai.ui.login

import android.os.Build
import androidx.lifecycle.LiveData
import androidx.lifecycle.MutableLiveData
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.launch
import me.matheesha.fanbotai.data.local.SettingsRepository
import me.matheesha.fanbotai.data.model.LoginResponse
import me.matheesha.fanbotai.data.repository.AuthRepository
import me.matheesha.fanbotai.data.repository.DeviceRepository
import me.matheesha.fanbotai.data.repository.Result
import me.matheesha.fanbotai.ui.UiState

class LoginViewModel(private val settings: SettingsRepository) : ViewModel() {
    private val authRepo   = AuthRepository(settings)
    private val deviceRepo = DeviceRepository(settings)

    private val _loginState = MutableLiveData<UiState<LoginResponse>>(UiState.Idle)
    val loginState: LiveData<UiState<LoginResponse>> = _loginState

    private val _needsTotp = MutableLiveData(false)
    val needsTotp: LiveData<Boolean> = _needsTotp

    fun login(username: String, password: String, totp: String? = null) {
        _loginState.value = UiState.Loading
        viewModelScope.launch {
            when (val result = authRepo.login(username, password, totp)) {
                is Result.Success -> {
                    val resp = result.data
                    when {
                        resp.needsTotp == true -> {
                            _needsTotp.value = true
                            _loginState.value = UiState.Idle
                        }
                        resp.ok == true -> {
                            resp.user?.let {
                                settings.setLoggedIn(true)
                                settings.setSavedUsername(it.username)
                                settings.setSavedRole(it.role)
                            }
                            val fcmToken = settings.getFcmToken()
                            if (fcmToken.isNotEmpty()) {
                                deviceRepo.registerDevice(fcmToken, Build.MODEL)
                            }
                            _loginState.value = UiState.Success(resp)
                        }
                        else -> _loginState.value = UiState.Error(resp.error ?: "Login failed")
                    }
                }
                is Result.Error -> _loginState.value = UiState.Error(result.message)
            }
        }
    }

    fun resetState() { _loginState.value = UiState.Idle; _needsTotp.value = false }
}

