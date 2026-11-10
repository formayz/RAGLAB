def saludar_estudiante(nombre):
    return f"Bienvenido, {nombre}. Ya estás listo para construir proyectos en Python."


def calcular_total(sesiones, horas_por_sesion):
    return sesiones * horas_por_sesion


def calcular_progreso(completados, total):
    if total == 0:
        return 0

    porcentaje = completados / total * 100
    return max(0, min(100, porcentaje))


nombre_estudiante = "formayz"

print(saludar_estudiante(nombre_estudiante))
print("Horas del módulo:", calcular_total(3, 2))
print("Progreso:", calcular_progreso(3, 4))
print("Progreso sin tareas:", calcular_progreso(0, 0))
