function getCurrentPosition(options = {}) {
  const mergedOptions = {
    enableHighAccuracy: true,
    timeout: 10000,
    maximumAge: 0,
    ...options,
  };

  return new Promise((resolve, reject) => {
    if (!navigator.geolocation) {
      reject(new Error("Geolocation is not supported in this browser."));
      return;
    }
    navigator.geolocation.getCurrentPosition(
      (position) =>
        resolve({
          latitude: position.coords.latitude,
          longitude: position.coords.longitude,
        }),
      (error) => {
        if (error.code === error.PERMISSION_DENIED) {
          reject(new Error("GPS permission denied."));
        } else if (error.code === error.TIMEOUT) {
          reject(new Error("GPS request timed out."));
        } else {
          reject(new Error("Could not fetch GPS location."));
        }
      },
      mergedOptions
    );
  });
}

window.getCurrentGps = getCurrentPosition;
